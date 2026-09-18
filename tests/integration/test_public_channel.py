"""The public door: what visitors to the hosted site can and cannot do.

Requests from the public reverse proxy carry x-ramcove-channel: public, set by the proxy. On that door
the operator, reviewer, validator and worker actions, the database reset and scenarios, the named demo
identities (whose keys are published) and file uploads are all refused. Visitors instead get a fresh
guest miner each, with simulated funds, so they can run the whole miner flow without sharing an identity.
"""

from __future__ import annotations

import dataclasses
import time

import pytest
from fastapi.testclient import TestClient
from ramcove_api.main import create_app
from ramcove_api.services import control
from ramcove_api.services.control import DEMO_REVIEW_REASON
from ramcove_api.store.db import tx
from ramcove_api.store.schema import guest_identities, reviews, submissions
from sqlalchemy import func, select

from .helpers import bring_workers_online, drain, make_ctx, pay_and_admit, state, submit_fixture

pytestmark = pytest.mark.db

PUBLIC = {"x-ramcove-channel": "public"}


@pytest.fixture
def ctx(tmp_path):
    return make_ctx(tmp_path)


def public_client(ctx) -> TestClient:
    # the hosted site is HTTPS end to end, and the public session cookie is Secure
    return TestClient(create_app(ctx), base_url="https://testserver", headers=PUBLIC)


@pytest.fixture
def public(ctx):
    return public_client(ctx)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/v1/demo/reset"),
        ("post", "/v1/demo/scenario"),
        ("post", "/v1/auth/demo"),
        ("get", "/v1/operator/console"),
        ("post", "/v1/worker/lease"),
        ("get", "/v1/review/queue"),
        ("get", "/v1/appeals"),
        ("get", "/v1/validator/workspace"),
        ("post", "/v1/miner/preflight"),
        ("get", "/openapi.json"),
    ],
)
def test_local_only_actions_are_refused_on_the_public_door(public, method, path):
    r = getattr(public, method)(path)
    assert r.status_code == 403, (path, r.status_code, r.text[:200])
    assert r.json()["error"]["code"] == "local_only"


def test_the_same_actions_still_work_locally(ctx):
    local = TestClient(create_app(ctx))
    assert local.post("/v1/auth/demo", json={"identity": "operator"}).status_code == 200
    assert local.get("/v1/operator/console").status_code == 200


def test_public_visitors_are_offered_only_a_guest_miner(public):
    body = public.get("/v1/demo/identities").json()
    assert body["identities"] == [] and body["guest"] is True


def test_each_visitor_gets_their_own_guest_miner_with_a_secure_cookie(ctx, public):
    first = public.post("/v1/auth/guest")
    assert first.status_code == 200, first.text
    assert first.json()["roles"] == ["miner"] and first.json()["guest"] is True
    assert "secure" in first.headers["set-cookie"].lower()
    other = public_client(ctx).post("/v1/auth/guest")
    assert other.json()["hotkey"] != first.json()["hotkey"]
    # the guest's key never leaves the server
    assert "seed" not in first.text.lower()


def test_a_guest_can_run_the_miner_flow(public):
    assert public.post("/v1/auth/guest").status_code == 200
    r = public.post("/v1/demo/submit-fixture", json={"fixture": "fragmentation-aware-allocator"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_guest_creation_is_rate_limited(ctx):
    ctx.settings = dataclasses.replace(ctx.settings, guest_limit_per_hour=2)
    codes = [public_client(ctx).post("/v1/auth/guest").status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    with tx(ctx.engine) as conn:
        assert conn.execute(select(func.count()).select_from(guest_identities)).scalar_one() == 2


def test_the_stand_in_reviewer_is_off_by_default_and_labels_what_it_approves(ctx):
    bring_workers_online(ctx)
    # triage is noisy (about one clear winner in eight is rejected), so resubmit as a miner would
    sub_id = None
    for _ in range(3):
        sub = submit_fixture(ctx, "miner-ada", "fragmentation-aware-allocator")
        pay_and_admit(ctx, sub["submission_id"], "miner-ada")
        drain(ctx)
        if state(ctx, sub["submission_id"]).state == "in_review":
            sub_id = sub["submission_id"]
            break
    assert sub_id, "no submission reached review in three attempts"
    assert control.auto_review(ctx) == 0  # off unless configured
    ctx.settings = dataclasses.replace(ctx.settings, demo_auto_review_s=1)
    time.sleep(1.2)
    assert control.auto_review(ctx) == 1
    with tx(ctx.engine) as conn:
        rv = conn.execute(select(reviews).where(reviews.c.submission_id == sub_id)).first()
        assert rv.decision == "approve" and rv.reasons == DEMO_REVIEW_REASON
        assert conn.execute(select(submissions.c.state).where(submissions.c.id == sub_id)).scalar_one() in {
            "ready_for_promotion",
            "promoted",
        }
