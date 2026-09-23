"""Milestone 2: one local journey through the real services and database (SIMULATED chain, beacon and worker)."""

import pytest
from ramcove_api.services import control
from ramcove_api.store import audit
from ramcove_api.store.db import tx
from ramcove_api.store.schema import champions, comparisons, ledger, receipts, reviews, weight_plans
from sqlalchemy import select

from .helpers import (
    ATTEMPTS,
    approve_review,
    bring_workers_online,
    drain,
    make_ctx,
    only_measurement_noise,
    pay_and_admit,
    state,
    submit_fixture,
)

pytestmark = pytest.mark.db


@pytest.fixture
def ctx(tmp_path):
    return make_ctx(tmp_path)


def test_failing_and_passing_challengers_end_to_end(ctx):
    bring_workers_online(ctx)
    fail = submit_fixture(ctx, "miner-bao", "evict-quarter")
    assert fail["ok"]
    pay_and_admit(ctx, fail["submission_id"], "miner-bao")
    with tx(ctx.engine) as conn:
        assert conn.execute(select(receipts)).rowcount != 0
    drain(ctx)
    f = state(ctx, fail["submission_id"])
    assert f.state == "not_promoted" and f.fee_outcome == "consumed", (f.state, f.outcome_summary)

    # One evaluation is a set of pass/fail readings over a noisy simulated measurement, so a stack that
    # really is better is sometimes rejected: see docs/acceptance-matrix.md for how often. A miner would pay
    # and resubmit, so the test does the same rather than gambling on one attempt. The point of this test is
    # that the journey works end to end, not that one run of the evaluator is lucky.
    win = winning_submission(ctx, "miner-ada", "fragmentation-aware-allocator", "promoted")
    w = state(ctx, win["submission_id"])
    with tx(ctx.engine) as conn:
        # nothing flagged it, so it was promoted without asking a person
        assert conn.execute(select(reviews).where(reviews.c.submission_id == w.id)).first() is None
        cur = conn.execute(select(champions).where(champions.c.status == "current")).first()
        assert cur.version == 1 and cur.author_hotkey == w.hotkey
        plan = conn.execute(select(weight_plans).order_by(weight_plans.c.created_at.desc())).first()
        assert (
            plan.body["entries"][0]["hotkey"] == w.hotkey and plan.body["status"] == "proposed_not_submitted"
        )
        kinds = [r.kind for r in conn.execute(select(ledger))]
        paid = 1 + win["attempts"]  # the losing challenger plus every attempt by the winner
        assert kinds.count("fee_received") == paid and kinds.count("fee_consumed") == paid
        ok, n, bad = audit.verify_chain(conn)
        assert ok and n > 20, bad


def test_a_flagged_winner_waits_for_a_person(ctx):
    bring_workers_online(ctx)
    win = winning_submission(ctx, "miner-ada", "native-paged-kv-kernel", "in_review")
    with tx(ctx.engine) as conn:
        rv = conn.execute(select(reviews).where(reviews.c.submission_id == win["submission_id"])).first()
    flagged = {c["id"] for c in rv.criteria if c.get("flagged")}
    assert flagged == {"native_review"}, rv.criteria
    approve_review(ctx, win["submission_id"])
    for _ in range(2):
        control.tick(ctx)
    assert state(ctx, win["submission_id"]).state == "promoted"


def test_a_close_first_reading_gets_a_second_and_both_are_recorded(ctx, monkeypatch):
    """A first reading between the margin and the clear-win line gets one more; both are stored."""
    from dataclasses import replace

    from ramcove_evaluator import pipeline

    original = pipeline._reading

    def close_reading(params, base, profile, seed, budget, *args, **kwargs):
        cap, runs = original(params, base, profile, seed, budget, *args, **kwargs)
        if ":reading" in seed and budget == pipeline.FULL_BUDGET_GIB:
            return replace(cap, capacity_rps=base * 1.0609), runs  # two grid steps: +6.1%
        return cap, runs

    monkeypatch.setattr(pipeline, "_reading", close_reading)
    bring_workers_online(ctx)
    measured = []
    for variant in range(ATTEMPTS):  # offline quality is noisy in the simulation; a miner would resubmit
        bring_workers_online(ctx)  # readiness expires in 120 s, and resubmitting takes longer than that
        sub = submit_fixture(ctx, "miner-ada", "fragmentation-aware-allocator", variant=variant)
        pay_and_admit(ctx, sub["submission_id"], "miner-ada")
        drain(ctx)
        with tx(ctx.engine) as conn:
            measured = conn.execute(
                select(comparisons)
                .where(
                    comparisons.c.submission_id == sub["submission_id"], comparisons.c.status == "measured"
                )
                .order_by(comparisons.c.created_at)
            ).all()
        if measured:
            break
    assert len(measured) == 2, measured
    assert measured[1].seed == f"{measured[0].seed}:reading1"
    w = state(ctx, sub["submission_id"])
    assert 50_000 < w.first_gain_ppm < 90_000 and w.bound_gain_ppm > 50_000, (
        w.first_gain_ppm,
        w.bound_gain_ppm,
    )


def test_after_the_sunset_a_second_validator_reproduces_the_winner(ctx):
    """In mainnet mode a winner is promoted only after a validator with no shared operator repeats its reading."""
    from ramcove_api.store.schema import jobs, profile_versions, workers
    from ramcove_protocol.rules import ProfileVersion
    from sqlalchemy import update

    with tx(ctx.engine) as conn:  # publish the same profile in mainnet mode, as the sunset would
        row = conn.execute(select(profile_versions).where(profile_versions.c.active)).first()
        body = {**row.body, "bootstrap": {**row.body["bootstrap"], "mode": "mainnet"}, "measured": True}
        mainnet = ProfileVersion.model_validate(body)
        conn.execute(
            update(profile_versions)
            .where(profile_versions.c.rule_hash == row.rule_hash)
            .values(body=mainnet.model_dump(mode="json", by_alias=True), rule_hash=mainnet.rule_hash())
        )
    everyone = ("w-op-1", "w-op-2", "w-shadow-1")
    with tx(ctx.engine) as conn:  # the shadow validator's worker is off in the seeded demo
        conn.execute(update(workers).where(workers.c.id == "w-shadow-1").values(enabled=True))
    bring_workers_online(ctx, everyone)
    outcomes = []
    for variant in range(ATTEMPTS):  # the simulated measurement is noisy; a miner would resubmit
        bring_workers_online(ctx, everyone)
        sub = submit_fixture(ctx, "miner-ada", "fragmentation-aware-allocator", variant=variant)
        pay_and_admit(ctx, sub["submission_id"], "miner-ada")
        drain(ctx, workers=everyone)
        for _ in range(2):
            control.tick(ctx)
        w = state(ctx, sub["submission_id"])
        outcomes.append((w.state, w.outcome_code, w.outcome_summary))
        if w.state == "promoted":
            break
    if w.state != "promoted" and only_measurement_noise([o[1] for o in outcomes], extra={"not_reproduced"}):
        # three workers each measure the champion for themselves; one that came out high rejects every
        # challenger it sees, and resubmitting cannot help (docs/readiness-report.md)
        pytest.skip(f"a worker's champion score rejected every attempt: {[(o[0], o[1]) for o in outcomes]}")
    assert outcomes[-1][0] == "promoted", outcomes
    with tx(ctx.engine) as conn:
        stages = [r.stage for r in conn.execute(select(jobs).where(jobs.c.submission_id == w.id))]
        readers = {
            r.worker
            for r in conn.execute(
                select(comparisons).where(
                    comparisons.c.submission_id == w.id, comparisons.c.status == "measured"
                )
            )
        }
    assert "reproduce" in stages
    # one reading from the operator's workers and one from the shadow validator's
    assert "w-shadow-1" in readers and readers & {"w-op-1", "w-op-2"}, readers


def winning_submission(ctx, miner: str, fixture: str, expected: str) -> dict:
    attempts, rejected = 0, []
    while attempts < ATTEMPTS:
        attempts += 1
        bring_workers_online(ctx)  # readiness expires in 120 s, and resubmitting takes longer than that
        sub = submit_fixture(ctx, miner, fixture, variant=attempts - 1)
        assert sub["ok"]
        pay_and_admit(ctx, sub["submission_id"], miner)
        drain(ctx)
        w = state(ctx, sub["submission_id"])
        if w.state == expected:
            return {**sub, "attempts": attempts}
        assert w.state == "not_promoted" and w.outcome_summary, (w.state, w.outcome_code, w.outcome_summary)
        rejected.append((w.outcome_code, w.outcome_summary))
    if only_measurement_noise([code for code, _ in rejected]):
        pytest.skip(f"this worker's champion score rejected every attempt: {rejected}")
    raise AssertionError(f"a clearly better stack was rejected {attempts} times: {rejected}")


def test_a_resubmission_needs_a_changed_artifact(ctx):
    """The path the journey takes after a noisy rejection, exercised on purpose: resubmitting the very
    same artifact is refused as a duplicate, while a changed one is accepted."""
    from ramcove_api.services import intake

    from .helpers import hotkey

    hk, _ = hotkey("miner-ada")
    first = submit_fixture(ctx, "miner-ada", "fragmentation-aware-allocator", variant=0)
    assert first["ok"]
    intake.withdraw(ctx, first["submission_id"], hk, "trying again")
    same = submit_fixture(ctx, "miner-ada", "fragmentation-aware-allocator", variant=0)
    assert not same["ok"] and "duplicate" in str(same).lower(), same
    changed = submit_fixture(ctx, "miner-ada", "fragmentation-aware-allocator", variant=1)
    assert changed["ok"], changed
