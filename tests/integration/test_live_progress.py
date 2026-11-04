"""What a running submission shows while it runs.

A stage can take hours on real hardware, so a worker says where it is and the public views repeat it.
It is display only: it never decides an outcome, and only the worker holding the lease may write it.
"""

from __future__ import annotations

import json

import pytest
from ramcove_api.services import public, queue
from ramcove_api.services.context import ServiceError
from ramcove_evaluator import pipeline
from ramcove_worker.runner import execute

from .helpers import (
    admit_submission,
    artifact_bytes,
    bring_workers_online,
    make_ctx,
    profile,
    provider,
    submit_fixture,
)

pytestmark = pytest.mark.db


@pytest.fixture
def ctx(tmp_path):
    return make_ctx(tmp_path)


def _lease_until(ctx, stage: str) -> dict:
    """Work through whatever the worker owes first (the champion's fixed score) until the wanted stage."""
    for _ in range(10):
        payload = queue.lease_next(ctx, "w-op-1")
        assert payload, "nothing to lease"
        if payload["stage"] == stage:
            return payload
        result = execute(payload, provider(), profile(ctx), lambda sha: artifact_bytes(ctx, sha))
        queue.complete(ctx, "w-op-1", payload["job_id"], json.loads(json.dumps(result, default=list)))
    raise AssertionError(f"no {stage} job appeared")


def test_a_running_stage_says_where_it_is(ctx):
    bring_workers_online(ctx)
    sub = submit_fixture(ctx, "miner-ada", "fragmentation-aware-allocator")
    admit_submission(ctx, sub["submission_id"], "miner-ada")
    payload = _lease_until(ctx, "screen")

    seen = []

    def report(event: dict) -> None:
        seen.append(event)
        queue.progress(ctx, "w-op-1", payload["job_id"], event)

    result = execute(payload, provider(), profile(ctx), lambda sha: artifact_bytes(ctx, sha), report)
    assert [e["step"] for e in seen] == ["screen_questions"] * len(seen) and seen
    assert seen[-1]["done"] == seen[-1]["total"]

    # the dashboard and the queue say the same thing, in words
    row = next(i for i in public.dashboard(ctx)["items"] if i["submission_id"] == sub["submission_id"])
    assert row["current_stage"]["progress_label"] == (
        f"Screening: {seen[-1]['total']:,} of {seen[-1]['total']:,} smoke questions answered"
    )
    q = next(
        i
        for i in public.queue_page(ctx, kind="admitted")["items"]
        if i["submission_id"] == sub["submission_id"]
    )
    assert q["current_stage"]["progress_label"] == row["current_stage"]["progress_label"]
    queue.complete(ctx, "w-op-1", payload["job_id"], json.loads(json.dumps(result, default=list)))


def test_only_the_lease_holder_may_report_and_only_known_steps(ctx):
    bring_workers_online(ctx)
    sub = submit_fixture(ctx, "miner-ada", "kv8-conversation-retention")
    admit_submission(ctx, sub["submission_id"], "miner-ada")
    payload = _lease_until(ctx, "screen")
    with pytest.raises(ServiceError) as other:
        queue.progress(ctx, "w-op-2", payload["job_id"], {"step": "quality", "done": 1, "total": 4000})
    assert other.value.code == "not_lease_holder"
    with pytest.raises(ServiceError) as bad:
        queue.progress(ctx, "w-op-1", payload["job_id"], {"step": "whatever it likes"})
    assert bad.value.code == "bad_progress"
    # fields that are not part of the vocabulary are dropped rather than stored
    stored = queue.progress(
        ctx, "w-op-1", payload["job_id"], {"step": "quality", "done": 300, "total": 4000, "note": "<b>"}
    )
    assert stored["progress"] == {"step": "quality", "done": 300, "total": 4000}


def test_an_evaluation_reports_every_part_of_the_workflow(ctx):
    """The evaluation itself emits the steps the dashboard shows, in order, without a worker or a database."""
    bring_workers_online(ctx)
    p = profile(ctx)
    from ramcove_evaluator.bank import build_bank
    from ramcove_evaluator.target import StackParams

    bank = build_bank("bank-test", "seed-test", p.question_bank)
    champion = StackParams("champion")
    calibration = pipeline.calibrate(champion, p, "cal", base_rps=0.5, bank=bank)
    seen: list[dict] = []
    pipeline.evaluate(
        StackParams("kv8", kv_factor=0.5),
        champion,
        p,
        "seed",
        calibration,
        bank,
        seen.append,
    )
    steps = [e["step"] for e in seen]
    assert steps[0] == "quality"
    assert "reading" in steps
    reading = next(e for e in seen if e["step"] == "reading")
    assert reading["run"] == 1 and reading["over_champion_ppm"] == 0
    assert public.progress_label(reading).startswith("Capacity reading 1: run 1 at the champion's score")


def test_the_dashboard_shows_the_workflow_itself(ctx):
    d = public.dashboard(ctx)
    keys = [w["key"] for w in d["workflow"]]
    assert keys == [
        "preflight",
        "admission",
        "screen",
        "quality",
        "reading",
        "rule",
        "winner_checks",
        "promotion",
    ]
    booked = next(w for w in d["workflow"] if w["key"] == "admission")
    with_checks = next(w for w in d["workflow"] if w["key"] == "winner_checks")
    # what a miner books covers screening and one evaluation; the winner checks come from the reserve
    assert "2.41 GPU-hours" in booked["what"] and "reserve" in with_checks["what"]
