"""The public door: what visitors to the hosted site can and cannot do.

Requests from the public reverse proxy carry x-ramcove-channel: public, set by the proxy. The hosted site
only reads: miners submit with the command line and validators run ramcove-validator. So on that door
every write is refused, and so are sign-in, personal data, the demo controls and every role's workspace.
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
from ramcove_api.store.schema import reviews, submissions
from sqlalchemy import func, select

from .helpers import (
    ATTEMPTS,
    bring_workers_online,
    drain,
    make_ctx,
    only_measurement_noise,
    pay_and_admit,
    state,
    submit_fixture,
)

pytestmark = pytest.mark.db

PUBLIC = {"x-ramcove-channel": "public"}


@pytest.fixture
def ctx(tmp_path):
    return make_ctx(tmp_path)


@pytest.fixture
def public(ctx):
    return TestClient(create_app(ctx), base_url="https://testserver", headers=PUBLIC)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/v1/demo/reset"),
        ("post", "/v1/demo/scenario"),
        ("post", "/v1/demo/submit-fixture"),
        ("get", "/v1/demo/identities"),
        ("post", "/v1/auth/demo"),
        ("post", "/v1/auth/challenge"),
        ("post", "/v1/auth/verify"),
        ("get", "/v1/auth/me"),
        ("get", "/v1/miner/submissions"),
        ("post", "/v1/miner/preflight"),
        ("get", "/v1/operator/console"),
        ("post", "/v1/worker/lease"),
        ("get", "/v1/review/queue"),
        ("get", "/v1/appeals"),
        ("get", "/v1/validator/workspace"),
        ("get", "/openapi.json"),
        # a write is refused even on a path whose read is public
        ("post", "/v1/dashboard"),
    ],
)
def test_the_public_door_refuses_sign_in_writes_and_workspaces(public, method, path):
    r = getattr(public, method)(path)
    assert r.status_code == 403, (path, r.status_code, r.text[:200])
    assert r.json()["error"]["code"] == "local_only"


@pytest.mark.parametrize(
    "path",
    [
        "/v1/meta",
        "/v1/overview",
        "/v1/dashboard",
        "/v1/profile",
        "/v1/status",
        "/v1/queue?kind=admitted",
        "/v1/question-banks",
        "/v1/champion-code",
    ],
)
def test_the_pages_the_site_shows_are_readable_on_the_public_door(public, path):
    assert public.get(path).status_code == 200, path


def test_the_same_actions_still_work_locally(ctx):
    local = TestClient(create_app(ctx))
    assert local.post("/v1/auth/demo", json={"identity": "operator"}).status_code == 200
    assert local.get("/v1/operator/console").status_code == 200


def test_there_is_no_guest_sign_in_any_more(ctx):
    local = TestClient(create_app(ctx))
    assert local.post("/v1/auth/guest").status_code in {404, 405}


def test_the_stand_in_reviewer_is_off_by_default_and_labels_what_it_approves(ctx):
    bring_workers_online(ctx)
    # a native kernel is flagged for a person; the simulated evaluation is noisy, so resubmit as a miner would
    sub_id, outcomes = None, []
    for attempt in range(ATTEMPTS):
        bring_workers_online(ctx)  # readiness expires in 120 s, and resubmitting takes longer than that
        sub = submit_fixture(ctx, "miner-ada", "native-paged-kv-kernel", variant=attempt)
        pay_and_admit(ctx, sub["submission_id"], "miner-ada")
        drain(ctx)
        st = state(ctx, sub["submission_id"])
        if st.state == "in_review":
            sub_id = sub["submission_id"]
            break
        outcomes.append(st.outcome_code)
    if not sub_id and only_measurement_noise(outcomes):
        pytest.skip(f"this worker's champion score rejected every attempt: {outcomes}")
    assert sub_id, f"no submission reached review in {ATTEMPTS} attempts: {outcomes}"
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


def test_the_waiting_list_is_shown_in_the_order_invitations_go_out(ctx):
    """The page numbers the waiting list, so its order must be the order the controller invites in."""
    from ramcove_api.services import public

    for miner, fixture in (
        ("miner-ada", "fragmentation-aware-allocator"),
        ("miner-bao", "kv8-conversation-retention"),
        ("miner-cyd", "native-paged-kv-kernel"),
    ):
        submit_fixture(ctx, miner, fixture)
    with tx(ctx.engine) as conn:  # no worker is online, so they are all waiting
        conn.execute(submissions.update().values(state="waitlisted", waitlisted_at=func.now()))
        rows = conn.execute(
            select(submissions.c.id)
            .where(submissions.c.state == "waitlisted")
            .order_by(submissions.c.waitlisted_at, submissions.c.id)
        ).all()
    waiting = public.queue_page(ctx, kind="waiting")["items"]
    assert [i["submission_id"] for i in waiting] == [r.id for r in rows]
