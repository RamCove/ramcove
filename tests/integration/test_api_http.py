"""HTTP behaviour and server-side authorization. Uses the real app, database and services."""

import hashlib
import json
import time

import pytest
from fastapi.testclient import TestClient
from ramcove_api.main import create_app
from ramcove_api.services.seed import worker_keypair
from ramcove_protocol.canonical import signing_payload

from .helpers import make_ctx, provider

pytestmark = pytest.mark.db


@pytest.fixture
def app_ctx(tmp_path):
    ctx = make_ctx(tmp_path)
    return create_app(ctx), ctx


@pytest.fixture
def client(app_ctx):
    app, _ = app_ctx
    return TestClient(app)


def sign_in(client: TestClient, identity: str) -> dict:
    r = client.post("/v1/auth/demo", json={"identity": identity})
    assert r.status_code == 200, r.text
    return r.json()


def worker_headers(ctx, worker_id: str, method: str, path: str, body: bytes) -> dict:
    kp = worker_keypair(worker_id)
    ts = int(time.time())
    payload = signing_payload(
        "worker_request",
        ctx.settings.network,
        {
            "worker": worker_id,
            "method": method,
            "path": path,
            "timestamp": ts,
            "body_sha256": hashlib.sha256(body).hexdigest(),
        },
    )
    return {
        "x-ramcove-worker": worker_id,
        "x-ramcove-timestamp": str(ts),
        "x-ramcove-signature": "0x" + kp.sign(payload).hex(),
        "content-type": "application/json",
    }


def test_public_pages_do_not_require_a_session(client):
    for path in ("/v1/meta", "/v1/overview", "/v1/profile", "/v1/queue", "/v1/status", "/v1/audit"):
        r = client.get(path)
        assert r.status_code == 200, (path, r.text)
    meta = client.get("/v1/meta").json()
    assert meta["simulated_chain"] and not meta["chain_writes_enabled"]
    ov = client.get("/v1/overview").json()
    assert ov["champion"]["version"] == 0 and ov["champion"]["is_baseline"]
    # king of the hill: only the baseline, so all five king slots are empty and their shares burn
    assert [(k["slot"], k["status"], k["share_bp"], k["eligible"]) for k in ov["kings"]] == [
        (slot, "empty", 2000, False) for slot in range(1, 6)
    ]


def test_preflight_requires_authentication(client):
    r = client.post("/v1/miner/preflight", files={"file": ("a.tar.gz", b"x")}, data={"signature": "0x00"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"


def test_miner_journey_over_http_and_idempotent_payment(client, app_ctx):
    app, ctx = app_ctx
    sign_in(client, "miner-ada")
    r = client.post("/v1/demo/submit-fixture", json={"fixture": "fragmentation-aware-allocator"})
    assert r.status_code == 200 and r.json()["ok"], r.text
    sub_id = r.json()["submission_id"]
    q = client.post(f"/v1/miner/submissions/{sub_id}/reserve", json={})
    assert q.status_code == 200 and q.json()["status"] == "waitlisted"  # no worker is ready yet
    # bring a worker online through the signed worker API
    body = json.dumps({"readiness": provider().readiness().as_dict()}).encode()
    hb = client.post(
        "/v1/worker/heartbeat",
        content=body,
        headers=worker_headers(ctx, "w-op-1", "POST", "/v1/worker/heartbeat", body),
    )
    assert hb.status_code == 200 and hb.json()["ready"]
    sign_in(client, "operator")
    assert client.post("/v1/demo/tick").status_code == 200
    sign_in(client, "miner-ada")
    q = client.post(f"/v1/miner/submissions/{sub_id}/reserve", json={})
    assert q.status_code == 200 and q.json()["status"] == "quoted", q.text
    quote = q.json()["quote"]
    assert quote["amount_rao"] > 0 and quote["remark"].startswith("ramcove:quote:")
    p1 = client.post(f"/v1/miner/quotes/{quote['quote_id']}/pay-simulated", headers={"idempotency-key": "k1"})
    p2 = client.post(f"/v1/miner/quotes/{quote['quote_id']}/pay-simulated", headers={"idempotency-key": "k1"})
    assert p1.status_code == 200 and p2.json().get("idempotent_replay") is True
    assert p1.json()["block_number"] == p2.json()["block_number"]  # no second payment on refresh
    sign_in(client, "operator")
    for _ in range(3):
        client.post("/v1/demo/tick")
    sign_in(client, "miner-ada")
    view = client.get(f"/v1/submissions/{sub_id}").json()
    assert view["state"] in ("admitted", "screening") and view["receipt"]["body"]["admission_key"][0] > 0
    mine = client.get("/v1/miner/submissions").json()
    assert mine["items"][0]["submission_id"] == sub_id


def test_private_fields_are_not_visible_to_other_miners(client, app_ctx):
    sign_in(client, "miner-ada")
    sub_id = client.post("/v1/demo/submit-fixture", json={"fixture": "kv8-conversation-retention"}).json()[
        "submission_id"
    ]
    own = client.get(f"/v1/submissions/{sub_id}").json()
    assert own["artifact_sha256"] and own["changed_paths"]
    sign_in(client, "miner-bao")
    other = client.get(f"/v1/submissions/{sub_id}").json()
    assert other["artifact_sha256"] is None and other["changed_paths"] is None
    assert other["hotkey"] != own["hotkey"] and "…" in other["hotkey"]


def test_roles_are_enforced_server_side(client):
    sign_in(client, "miner-ada")
    assert client.get("/v1/operator/console").status_code == 403
    assert client.post("/v1/operator/intake", json={"paused": True, "reason": "attempt"}).status_code == 403
    assert client.get("/v1/review/queue").status_code == 403
    assert client.post("/v1/demo/reset").status_code == 403
    sign_in(client, "reviewer-1")
    assert client.get("/v1/review/queue").status_code == 200
    assert client.get("/v1/operator/console").status_code == 403
    sign_in(client, "operator")
    assert client.get("/v1/operator/console").status_code == 200


def test_worker_requests_need_a_valid_signature(client, app_ctx):
    app, ctx = app_ctx
    body = json.dumps({"readiness": {"safe_and_ready": True}}).encode()
    assert client.post("/v1/worker/heartbeat", content=body).status_code == 401
    bad = worker_headers(ctx, "w-op-1", "POST", "/v1/worker/heartbeat", b"different-body")
    assert client.post("/v1/worker/heartbeat", content=body, headers=bad).status_code == 401
    good = worker_headers(ctx, "w-op-1", "POST", "/v1/worker/heartbeat", body)
    stale = {**good, "x-ramcove-timestamp": str(int(time.time()) - 600)}
    assert client.post("/v1/worker/heartbeat", content=body, headers=stale).status_code == 401
    assert client.post("/v1/worker/heartbeat", content=body, headers=good).status_code == 200


def test_cross_site_post_is_refused(client):
    sign_in(client, "miner-ada")
    r = client.post(
        "/v1/demo/submit-fixture",
        json={"fixture": "kv8-conversation-retention"},
        headers={"origin": "https://evil.example"},
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "bad_origin"


def test_one_active_submission_per_hotkey(client):
    sign_in(client, "miner-cyd")
    first = client.post("/v1/demo/submit-fixture", json={"fixture": "kv8-conversation-retention"})
    assert first.json()["ok"]
    second = client.post("/v1/demo/submit-fixture", json={"fixture": "fragmentation-aware-allocator"})
    assert second.status_code == 409 and second.json()["error"]["code"] == "active_limit"


def test_untrusted_artifact_passes_preflight_but_cannot_be_quoted(client, app_ctx):
    """No isolation backend for untrusted code: free checks still run, paid admission does not."""
    app, ctx = app_ctx
    from ramcove_api.services.auth import demo_keypair
    from ramcove_miner.artifact import pack, sign_artifact

    sign_in(client, "miner-dee")
    with __import__("ramcove_api.store.db", fromlist=["tx"]).tx(ctx.engine) as conn:
        profile = ctx.profile(conn)
    manifest = {
        "schema": "ramcove.manifest/1",
        "profile_id": profile.profile_id,
        "profile_version": profile.version,
        "hotkey": None,
        "lineage": "hand-written",
        "parent_champion_version": 0,
        "method": "A hand written patch that is not a repository fixture.",
        "mechanism": "allocation",
        "license": "Apache-2.0",
        "third_party": [],
    }
    kp = demo_keypair(ctx, client.get("/v1/auth/me").json()["session"]["hotkey"])
    manifest["hotkey"] = kp.ss58_address
    patch = (
        "diff --git a/vllm/v1/core/kv_cache_manager.py b/vllm/v1/core/kv_cache_manager.py\n"
        "--- a/vllm/v1/core/kv_cache_manager.py\n+++ b/vllm/v1/core/kv_cache_manager.py\n"
        "@@ -1,2 +1,3 @@\n # cache\n+CUSTOM = 1\n"
    )
    data = pack(manifest, patch)
    sig = sign_artifact(kp, data, ctx.settings.network, profile.profile_id, profile.version)
    r = client.post("/v1/miner/preflight", files={"file": ("a.tar.gz", data)}, data={"signature": sig})
    assert r.status_code == 200 and r.json()["ok"] and r.json()["trusted_fixture"] is None
    sub_id = r.json()["submission_id"]
    body = json.dumps({"readiness": provider().readiness().as_dict()}).encode()
    client.post(
        "/v1/worker/heartbeat",
        content=body,
        headers=worker_headers(ctx, "w-op-1", "POST", "/v1/worker/heartbeat", body),
    )
    q = client.post(f"/v1/miner/submissions/{sub_id}/reserve", json={})
    assert q.json()["status"] == "waitlisted" and "capacity" in q.json()


def test_lock_contention_is_a_retryable_busy_answer_not_an_internal_error(app_ctx, monkeypatch):
    from psycopg.errors import LockNotAvailable
    from ramcove_api.services import public
    from sqlalchemy.exc import OperationalError

    def busy(*_a, **_k):
        raise OperationalError("SELECT pg_advisory_xact_lock(...)", {}, LockNotAvailable("lock timeout"))

    monkeypatch.setattr(public, "status_page", busy)
    app, _ = app_ctx
    r = TestClient(app, raise_server_exceptions=False).get("/v1/status")
    assert r.status_code == 503
    assert r.headers["retry-after"] == "2"
    assert r.json()["error"]["code"] == "busy"
    assert "reference" not in r.json()["error"]


def test_dashboard_groups_every_submission_and_shows_only_public_fields(client):
    r = client.get("/v1/dashboard")
    assert r.status_code == 200
    d = r.json()
    assert set(d["counts"]) == {"in_progress", "waiting", "promoted", "rejected", "closed"}
    assert d["total"] == sum(d["counts"].values())
    assert d["champion"]["version"] >= 0
    for item in d["items"]:
        assert item["group"] in d["counts"]
        assert item["hotkey"] is None or "\u2026" in item["hotkey"]  # masked
        assert not {"payment", "quote", "receipt", "changed_paths"} & set(item)
