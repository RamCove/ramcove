"""Demo scenarios run one after another on the live demo, so a later one must respect earlier state."""

from __future__ import annotations

import pytest
from ramcove_api.services.scenarios import run

from .helpers import admit_submission, bring_workers_online, make_ctx, state, submit_fixture

pytestmark = pytest.mark.db


@pytest.fixture
def ctx(tmp_path):
    return make_ctx(tmp_path)


def test_live_after_busy_skips_a_miner_still_in_review_and_shows_the_registration_rule(ctx):
    # "busy" leaves miner-cyd's flagged winner waiting for a reviewer: an active submission
    bring_workers_online(ctx)
    held = submit_fixture(ctx, "miner-cyd", "native-paged-kv-kernel")
    admit_submission(ctx, held["submission_id"], "miner-cyd")

    out = run(ctx, "live")

    assert out["skipped"]["miner-cyd"] == "already has an active submission"
    assert state(ctx, out["submissions"]["fragmentation-aware-allocator"]).state == "admitted"
    assert state(ctx, out["submissions"]["kv8-conversation-retention"]).state == "admitted"
    # miner-dee is the unregistered demo miner: free checks pass, joining the queue waits for registration
    assert "not registered" in out["skipped"]["miner-dee"]
    assert state(ctx, out["submissions"]["evict-quarter"]).state == "preflight_passed"
