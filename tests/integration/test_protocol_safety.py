"""Race, replay, ordering and fail-closed behaviour against the real database."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from ramcove_api.services import control, intake, payments, queue, settlement
from ramcove_api.services.context import ServiceError
from ramcove_api.store.db import now, tx
from ramcove_api.store.schema import (
    champion_pointer,
    champions,
    credits,
    identities,
    jobs,
    ledger,
    price_observations,
    receipts,
    submissions,
)
from ramcove_api.store.schema import (
    payments as payments_t,
)
from ramcove_miner.artifact import pack, sign_artifact
from ramcove_miner.fixtures import by_name, manifest_for
from ramcove_protocol.state import S
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from substrateinterface import Keypair

from .helpers import bring_workers_online, make_ctx, state

pytestmark = pytest.mark.db


@pytest.fixture
def ctx(tmp_path):
    c = make_ctx(tmp_path)
    bring_workers_online(c)
    return c


def allow_untrusted(ctx) -> None:
    """Test-only: pretend the workers have a real isolation boundary, so arbitrary artifacts are admitted.

    Production readiness comes from the provider's own probes; this only exercises the queue arithmetic.
    """
    from ramcove_api.store.schema import workers

    with tx(ctx.engine) as conn:
        for w in conn.execute(select(workers)).all():
            conn.execute(
                update(workers)
                .where(workers.c.id == w.id)
                .values(readiness={**w.readiness, "untrusted_code_isolation": True})
            )


def pretend_calibrated(ctx, capacity_milli: int = 500) -> None:
    """Test-only: skip the (simulated) calibration run so a test can lease the stage it cares about."""
    from ramcove_api.store.schema import workers

    with tx(ctx.engine) as conn:
        for w in conn.execute(select(workers)).all():
            conn.execute(
                update(workers)
                .where(workers.c.id == w.id)
                .values(
                    calibrated_champion_version=0,
                    calibrated_at=now(),
                    readiness={
                        **w.readiness,
                        "calibration": {
                            "capacity_milli_rps": capacity_milli,
                            "tight_capacity_milli_rps": int(capacity_milli * 0.85),
                            "flag": "ok",
                        },
                    },
                )
            )


def unique_submission(ctx, index: int, fixture: str = "fragmentation-aware-allocator") -> tuple[str, str]:
    """A distinct miner and a distinct patch, so neither the hotkey nor the duplicate check interferes."""
    kp = Keypair.create_from_uri(f"//RaceMiner{index}")
    with tx(ctx.engine) as conn:
        conn.execute(
            insert(identities)
            .values(hotkey=kp.ss58_address, display_name=f"race {index}", demo=True)
            .on_conflict_do_nothing()
        )
        profile = ctx.profile(conn)
    fx = by_name(fixture)
    manifest = manifest_for(fx, kp.ss58_address, profile.profile_id, profile.version, 0)
    manifest["lineage"] = f"race-{index}"
    patch = fx["patch"] + f"+RACE_{index} = 1\n"
    data = pack(manifest, patch)
    sig = sign_artifact(kp, data, ctx.settings.network, profile.profile_id, profile.version)
    r = intake.preflight(ctx, kp.ss58_address, data, sig)
    assert r["ok"], r["errors"]
    with tx(ctx.engine) as conn:  # a champion must be registered to receive weight
        ctx.chain(conn).store.register(ctx.settings.netuid, kp.ss58_address)
    return r["submission_id"], kp.ss58_address


def test_simultaneous_quotes_cannot_oversell_capacity(ctx):
    allow_untrusted(ctx)
    subs = [unique_submission(ctx, i) for i in range(14)]
    filler, _ = unique_submission(ctx, 14)
    with tx(ctx.engine) as conn:
        profile = ctx.profile(conn)
        plan = ctx.capacity_plan(conn, profile, trusted_fixture=True)
        # most of the two-week queue is already booked, so only five more evaluations fit
        fits = 5
        conn.execute(
            update(submissions)
            .where(submissions.c.id == filler)
            .values(reserved_centi=plan.capacity_centi() - fits * profile.envelope.total())
        )

    def reserve(pair):
        sub_id, hotkey = pair
        try:
            return intake.reserve(ctx, sub_id, hotkey, hotkey)["status"]
        except ServiceError as e:  # pragma: no cover - surfaced as a failure below
            return f"error:{e.code}"

    with ThreadPoolExecutor(max_workers=14) as pool:
        results = list(pool.map(reserve, subs))
    quoted = results.count("quoted")
    assert quoted == fits, results
    assert results.count("waitlisted") == 14 - fits
    with tx(ctx.engine) as conn:
        committed = ctx.committed_centi(conn, profile.profile_id)
    assert committed <= plan.capacity_centi()


def test_replaying_a_payment_cannot_admit_twice(ctx):
    allow_untrusted(ctx)
    sub_id, hotkey = unique_submission(ctx, 100)
    q = intake.reserve(ctx, sub_id, hotkey, hotkey)
    intake.demo_pay(ctx, q["quote"]["quote_id"], hotkey)
    for _ in range(3):
        control.tick(ctx)
    with tx(ctx.engine) as conn:
        assert conn.execute(select(func.count()).select_from(receipts)).scalar() == 1
        chain = ctx.chain(conn)
        ext = [
            e
            for e in chain.extrinsics(conn.execute(select(payments_t.c.block_number)).scalar())
            if e.index == 0
        ][0]
        # replay the same extrinsic several times, exactly as a restarted scanner would
        for _ in range(3):
            payments.process_extrinsic(conn, ctx, ext)
    with tx(ctx.engine) as conn:
        assert conn.execute(select(func.count()).select_from(receipts)).scalar() == 1
        assert conn.execute(select(func.count()).select_from(payments_t)).scalar() == 1
        fee_rows = conn.execute(
            select(func.count()).select_from(ledger).where(ledger.c.kind == "fee_received")
        ).scalar()
        assert fee_rows == 1


def test_second_payment_for_the_same_quote_is_refunded_not_admitted(ctx):
    allow_untrusted(ctx)
    sub_id, hotkey = unique_submission(ctx, 101)
    q = intake.reserve(ctx, sub_id, hotkey, hotkey)
    intake.demo_pay(ctx, q["quote"]["quote_id"], hotkey)
    for _ in range(3):
        control.tick(ctx)
    with tx(ctx.engine) as conn:  # the miner pays a second time by mistake
        chain = ctx.chain(conn)
        from ramcove_chain.devchain import payment_call

        chain.produce_block(
            [(hotkey, payment_call(ctx.evaluation_wallet, q["quote"]["amount_rao"], q["quote"]["quote_id"]))]
        )
    for _ in range(3):
        control.tick(ctx)
    with tx(ctx.engine) as conn:
        assert conn.execute(select(func.count()).select_from(receipts)).scalar() == 1
        outcomes = [r.outcome for r in conn.execute(select(payments_t))]
        assert sorted(outcomes) == ["rejected", "verified"]
        from ramcove_api.store.schema import refunds

        assert conn.execute(select(func.count()).select_from(refunds)).scalar() == 1


def test_underpayment_is_rejected_and_opens_a_refund(ctx):
    allow_untrusted(ctx)
    sub_id, hotkey = unique_submission(ctx, 102)
    q = intake.reserve(ctx, sub_id, hotkey, hotkey)
    intake.demo_pay(ctx, q["quote"]["quote_id"], hotkey, amount_override=q["quote"]["amount_rao"] // 2)
    for _ in range(3):
        control.tick(ctx)
    assert state(ctx, sub_id).state == S.QUOTED
    with tx(ctx.engine) as conn:
        from ramcove_api.store.schema import refunds

        r = conn.execute(select(refunds)).first()
        assert r is not None and "underpaid" in r.reason


def test_a_stale_price_does_not_block_the_flat_fee(ctx):
    allow_untrusted(ctx)
    sub_id, hotkey = unique_submission(ctx, 103)
    with tx(ctx.engine) as conn:
        conn.execute(update(price_observations).values(observed_at=now() - timedelta(hours=2)))
    q = intake.reserve(ctx, sub_id, hotkey, hotkey)
    assert q["status"] == "quoted" and q["quote"]["amount_rao"] == 100_000_000
    assert q["quote"]["price_usd_micros"] is None and q["display"]["fee_usd_cents_at_price"] is None


def test_paused_intake_and_no_ready_worker_fail_closed(ctx):
    allow_untrusted(ctx)
    sub_id, hotkey = unique_submission(ctx, 104)
    from ramcove_api.store.schema import settings as settings_t
    from ramcove_api.store.schema import workers

    with tx(ctx.engine) as conn:
        conn.execute(
            update(settings_t).where(settings_t.c.key == "intake_paused").values(value={"paused": True})
        )
    assert intake.reserve(ctx, sub_id, hotkey, hotkey)["status"] == "waitlisted"
    with tx(ctx.engine) as conn:
        conn.execute(
            update(settings_t).where(settings_t.c.key == "intake_paused").values(value={"paused": False})
        )
        conn.execute(update(workers).values(ready=False))
    sub2, hk2 = unique_submission(ctx, 105)
    assert intake.reserve(ctx, sub2, hk2, hk2)["status"] == "waitlisted"


def test_untrusted_artifact_is_never_leased_to_a_fixtures_only_worker(ctx):
    """Fail closed: a worker without untrusted-code isolation is not given an unknown artifact."""
    kp = Keypair.create_from_uri("//UntrustedMiner")
    with tx(ctx.engine) as conn:
        conn.execute(insert(identities).values(hotkey=kp.ss58_address, demo=True).on_conflict_do_nothing())
        profile = ctx.profile(conn)
    manifest = manifest_for(
        by_name("fragmentation-aware-allocator"), kp.ss58_address, profile.profile_id, profile.version, 0
    )
    manifest["lineage"] = "hand-written"
    patch = (
        "diff --git a/vllm/v1/core/kv_cache_manager.py b/vllm/v1/core/kv_cache_manager.py\n"
        "--- a/vllm/v1/core/kv_cache_manager.py\n+++ b/vllm/v1/core/kv_cache_manager.py\n"
        "@@ -1,2 +1,3 @@\n # cache\n+UNTRUSTED = 1\n"
    )
    data = pack(manifest, patch)
    sig = sign_artifact(kp, data, ctx.settings.network, profile.profile_id, profile.version)
    r = intake.preflight(ctx, kp.ss58_address, data, sig)
    assert r["ok"] and r["trusted_fixture"] is None
    assert intake.reserve(ctx, r["submission_id"], kp.ss58_address, kp.ss58_address)["status"] == "waitlisted"


def test_worker_payload_carries_no_credentials(ctx):
    allow_untrusted(ctx)
    sub_id, hotkey = unique_submission(ctx, 106)
    pay_and_admit_like(ctx, sub_id, hotkey)
    payload = queue.lease_next(ctx, "w-op-1")
    blob = json.dumps(payload).lower()
    for secret in ("password", "postgres", "ghp_", "database_url", "//ramcovedemo", "token", "private"):
        assert secret not in blob, (secret, blob[:200])


def pay_and_admit_like(ctx, sub_id: str, hotkey: str) -> None:
    q = intake.reserve(ctx, sub_id, hotkey, hotkey)
    assert q["status"] == "quoted", q
    intake.demo_pay(ctx, q["quote"]["quote_id"], hotkey)
    for _ in range(3):
        control.tick(ctx)


def test_lease_expiry_keeps_priority_then_ends_as_operator_failure(ctx):
    allow_untrusted(ctx)
    pretend_calibrated(ctx)
    sub_id, hotkey = unique_submission(ctx, 107)
    pay_and_admit_like(ctx, sub_id, hotkey)
    leased = queue.lease_next(ctx, "w-op-1")
    assert leased["stage"] == "screen"
    with tx(ctx.engine) as conn:
        conn.execute(update(jobs).where(jobs.c.submission_id == sub_id).values(lease_expires_at=now()))
        queue.expire_leases(conn, ctx)
    assert state(ctx, sub_id).state == S.ADMITTED  # requeued, priority kept
    with tx(ctx.engine) as conn:
        job = conn.execute(select(jobs).where(jobs.c.submission_id == sub_id)).first()
        assert job.status == "queued" and job.attempts == 1
    queue.lease_next(ctx, "w-op-1")
    with tx(ctx.engine) as conn:
        conn.execute(update(jobs).where(jobs.c.submission_id == sub_id).values(lease_expires_at=now()))
        queue.expire_leases(conn, ctx)
    row = state(ctx, sub_id)
    assert row.state == S.OPERATOR_FAILED and row.fee_outcome == "refund_or_credit"
    with tx(ctx.engine) as conn:
        assert conn.execute(select(func.count()).select_from(credits)).scalar() == 1


def test_modified_artifact_cannot_inherit_an_earlier_result(ctx):
    """A revised artifact is a new submission: new hash, new admission key, no inherited measurements."""
    allow_untrusted(ctx)
    pretend_calibrated(ctx)
    sub_id, hotkey = unique_submission(ctx, 108)
    pay_and_admit_like(ctx, sub_id, hotkey)
    with tx(ctx.engine) as conn:
        conn.execute(
            update(submissions)
            .where(submissions.c.id == sub_id)
            .values(first_gain_ppm=400_000, bound_gain_ppm=300_000)
        )
        original = conn.execute(select(submissions).where(submissions.c.id == sub_id)).first()
    intake.withdraw(ctx, sub_id, hotkey, "revising the patch")
    revised_id, _ = unique_submission(ctx, 1081)
    with tx(ctx.engine) as conn:
        revised = conn.execute(select(submissions).where(submissions.c.id == revised_id)).first()
    assert revised.id != original.id
    assert revised.artifact_sha256 != original.artifact_sha256
    assert revised.admission_block is None
    assert revised.first_gain_ppm is None and revised.bound_gain_ppm is None
    assert revised.state == S.PREFLIGHT_PASSED


def test_two_promotions_cannot_both_win_with_the_same_compared_version(ctx):
    allow_untrusted(ctx)
    """Compare-and-set: only one promotion can move the champion pointer from v0."""
    a, hk_a = unique_submission(ctx, 109)
    b, hk_b = unique_submission(ctx, 110, fixture="kv8-conversation-retention")
    for sub, hk in ((a, hk_a), (b, hk_b)):
        pay_and_admit_like(ctx, sub, hk)
    with tx(ctx.engine) as conn:
        profile = ctx.profile(conn)
        for sub in (a, b):
            conn.execute(
                update(submissions)
                .where(submissions.c.id == sub)
                .values(
                    state=S.READY_FOR_PROMOTION.value,
                    compared_champion_version=0,
                    compared_rule_hash=profile.rule_hash(),
                    ready_since=now(),
                    bound_gain_ppm=200_000,
                )
            )
    with tx(ctx.engine) as conn:
        sub_a = conn.execute(select(submissions).where(submissions.c.id == a)).first()
        sub_b = conn.execute(select(submissions).where(submissions.c.id == b)).first()
        assert settlement.promote(conn, ctx, profile, sub_a, 0) is True
        assert settlement.promote(conn, ctx, profile, sub_b, 0) is False  # pointer already moved
    with tx(ctx.engine) as conn:
        assert conn.execute(select(champion_pointer.c.version)).scalar() == 1
        current = conn.execute(select(champions).where(champions.c.status == "current")).all()
        assert len(current) == 1 and current[0].submission_id == a


def test_earlier_active_admission_blocks_a_later_promotion(ctx):
    allow_untrusted(ctx)
    early, hk_e = unique_submission(ctx, 111)
    later, hk_l = unique_submission(ctx, 112, fixture="kv8-conversation-retention")
    pay_and_admit_like(ctx, early, hk_e)
    pay_and_admit_like(ctx, later, hk_l)
    with tx(ctx.engine) as conn:
        profile = ctx.profile(conn)
        conn.execute(
            update(submissions)
            .where(submissions.c.id == later)
            .values(
                state=S.READY_FOR_PROMOTION.value,
                compared_champion_version=0,
                compared_rule_hash=profile.rule_hash(),
                ready_since=now(),
                bound_gain_ppm=200_000,
            )
        )
        actions = settlement.settle(conn, ctx, profile.profile_id)
    assert any(a["action"] == "wait" and early in a.get("blocking", []) for a in actions), actions
    with tx(ctx.engine) as conn:
        assert conn.execute(select(champion_pointer.c.version)).scalar() == 0
    # the earlier admission reaches a terminal state: the barrier releases
    intake.withdraw(ctx, early, hk_e, "no longer needed")
    with tx(ctx.engine) as conn:
        actions = settlement.settle(conn, ctx, profile.profile_id)
    assert any(a["action"] == "promoted" for a in actions), actions


@pytest.mark.parametrize(
    ("new_champion_gain", "outcome", "gain_over_new"),
    [(100_000, S.PROMOTED, 181_818), (250_000, S.NOT_PROMOTED, 40_000)],
)
def test_a_winner_measured_against_an_old_champion_is_re_compared_not_re_measured(
    ctx, new_champion_gain, outcome, gain_over_new
):
    allow_untrusted(ctx)
    a, hk_a = unique_submission(ctx, 113)
    pay_and_admit_like(ctx, a, hk_a)
    with tx(ctx.engine) as conn:
        profile = ctx.profile(conn)
        # v1 is crowned while this submission, measured +30% over v0, waits its turn
        conn.execute(update(champion_pointer).values(version=1))
        conn.execute(update(champions).where(champions.c.version == 0).values(status="superseded"))
        conn.execute(
            champions.insert().values(
                profile_id=profile.profile_id,
                version=1,
                rule_hash=profile.rule_hash(),
                status="current",
                attribution={},
                author_hotkey=None,
                bound_gain_ppm=new_champion_gain,
            )
        )
        conn.execute(update(jobs).where(jobs.c.submission_id == a).values(status="done"))
        conn.execute(
            update(submissions)
            .where(submissions.c.id == a)
            .values(
                state=S.READY_FOR_PROMOTION.value,
                compared_champion_version=0,
                compared_rule_hash=profile.rule_hash(),
                ready_since=now(),
                bound_gain_ppm=300_000,
            )
        )
        actions = settlement.settle(conn, ctx, profile.profile_id)
        actions += settlement.settle(conn, ctx, profile.profile_id)
    assert actions[0]["action"] == "recompare", actions
    row = state(ctx, a)
    # 1.30 / 1.10 - 1 = 18.2% still clears the 5% margin; 1.30 / 1.25 - 1 = 4.0% does not
    assert row.state == outcome and abs(row.bound_gain_ppm - gain_over_new) <= 1, (
        row.state,
        row.bound_gain_ppm,
    )
    with tx(ctx.engine) as conn:
        open_jobs = conn.execute(
            select(func.count())
            .select_from(jobs)
            .where(jobs.c.submission_id == a, jobs.c.status.in_(["queued", "leased"]))
        ).scalar()
    assert open_jobs == 0  # nothing is measured again
