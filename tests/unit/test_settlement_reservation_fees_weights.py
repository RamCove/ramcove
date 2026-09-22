from datetime import UTC, datetime, timedelta

import pytest
from ramcove_protocol.fees import PriceObservation, compute_fee
from ramcove_protocol.money import RAO_PER_TAO
from ramcove_protocol.reservation import CapacityPlan, can_issue_quote, remaining_envelope
from ramcove_protocol.settlement import AdmissionKey, QueueEntry, decide_promotion
from ramcove_protocol.state import TERMINAL, S, TransitionError, fee_outcome, next_state
from ramcove_protocol.weights import ChampionState, UidSnapshot, build_weight_plan

RH = "rulehash"


def entry(sid, block, state, version=0, registered=True, idx=0):
    return QueueEntry(sid, "p1", AdmissionKey(block, idx), S(state), version, RH, registered)


def test_earlier_job_still_in_full_evaluation_blocks_later_promotion():
    """Review R2: A paid first and is still evaluating; B finished first. B must wait."""
    a = entry("A", 100, S.EVALUATING)
    b = entry("B", 101, S.READY_FOR_PROMOTION)
    d = decide_promotion(b, [a, b], 0, RH, registration_expired=False)
    assert not d.allowed and d.action == "wait" and d.blocking == ("A",)


def test_earlier_job_still_screening_blocks_too():
    a = entry("A", 100, S.ADMITTED)
    b = entry("B", 101, S.READY_FOR_PROMOTION)
    assert decide_promotion(b, [a, b], 0, RH, False).action == "wait"


def test_same_block_uses_extrinsic_index():
    a = entry("A", 100, S.SCREENING, idx=3)
    b = entry("B", 100, S.READY_FOR_PROMOTION, idx=7)
    assert decide_promotion(b, [a, b], 0, RH, False).blocking == ("A",)


def test_lease_expiry_requeue_keeps_priority():
    assert next_state(S.EVALUATING, "lease_expired") == S.EVAL_QUEUED
    a = entry("A", 100, S.EVAL_QUEUED)
    b = entry("B", 101, S.READY_FOR_PROMOTION)
    assert decide_promotion(b, [a, b], 0, RH, False).blocking == ("A",)


@pytest.mark.parametrize("terminal", [S.NOT_PROMOTED, S.OPERATOR_FAILED, S.REJECTED_SCREEN, S.WITHDRAWN])
def test_terminal_earlier_job_releases_barrier(terminal):
    a = entry("A", 100, terminal)
    b = entry("B", 101, S.READY_FOR_PROMOTION)
    assert decide_promotion(b, [a, b], 0, RH, False).allowed


def test_evidence_against_an_older_champion_is_re_compared_not_re_measured():
    b = entry("B", 101, S.READY_FOR_PROMOTION, version=1)
    assert decide_promotion(b, [b], 2, RH, False).action == "recompare"
    b2 = QueueEntry("B", "p1", AdmissionKey(101, 0), S.READY_FOR_PROMOTION, 2, "other-rule", True)
    assert decide_promotion(b2, [b2], 2, RH, False).action == "recompare"


def test_registration_precedes_title_transfer():
    b = entry("B", 101, S.READY_FOR_PROMOTION, registered=False)
    d = decide_promotion(b, [b], 0, RH, registration_expired=False)
    assert not d.allowed and "incumbent keeps" in d.reason
    assert decide_promotion(b, [b], 0, RH, registration_expired=True).action == "expire_registration"


def test_terminal_states_cannot_move():
    for t in TERMINAL:
        with pytest.raises(TransitionError):
            next_state(t, "promote")


def test_operator_failures_never_consume_fee():
    assert fee_outcome(S.OPERATOR_FAILED) == "refund_or_credit"


def test_booked_work_never_exceeds_the_two_week_queue(profile):
    env = profile.envelope
    plan = CapacityPlan(workers_ready=2, horizon_hours=336)
    committed = 0
    admitted = 0
    for _ in range(1000):  # a flood of submissions
        check = can_issue_quote(committed, env, plan, intake_paused=False)
        if not check.allowed:
            break
        committed += remaining_envelope(S.ADMITTED, env)
        admitted += 1
    # each admission books screening plus one evaluation; the reserve covers winners' extra checks
    assert env.total() == 316
    assert committed <= plan.capacity_centi() < committed + env.total()
    assert admitted == plan.capacity_centi() // env.total() == 170


def test_envelope_releases_as_outcomes_are_known(profile):
    env = profile.envelope
    seq = [S.ADMITTED, S.EVAL_QUEUED, S.IN_REVIEW, S.READY_FOR_PROMOTION, S.PROMOTED]
    values = [remaining_envelope(s, env) for s in seq]
    assert values == [316, 299, 0, 0, 0]


def test_no_quotes_when_paused_or_no_safe_workers(profile):
    assert not can_issue_quote(0, profile.envelope, CapacityPlan(2, 336), intake_paused=True).allowed
    assert not can_issue_quote(0, profile.envelope, CapacityPlan(0, 336), intake_paused=False).allowed


def test_the_fee_is_a_flat_tenth_of_a_tao(profile):
    now = datetime(2026, 9, 17, 15, 40, tzinfo=UTC)
    price = PriceObservation("coingecko:bittensor:usd", 227_920_000, now - timedelta(minutes=4), False)
    f = compute_fee(profile.fees, price, now)
    assert f.fee_rao == RAO_PER_TAO // 10  # 0.1 TAO
    assert f.fee_usd_cents_at_price == 2279  # $22.79 at $227.92, shown for information only
    doubled = PriceObservation("coingecko:bittensor:usd", 455_840_000, now - timedelta(minutes=4), False)
    assert compute_fee(profile.fees, doubled, now).fee_rao == f.fee_rao  # the price never moves the fee


def test_a_stale_or_foreign_price_only_hides_the_dollar_value(profile):
    now = datetime(2026, 9, 17, tzinfo=UTC)
    stale = PriceObservation("coingecko:bittensor:usd", 227_920_000, now - timedelta(hours=1), False)
    foreign = PriceObservation("somewhere-else", 227_920_000, now, False)
    for price in (stale, foreign, None):
        f = compute_fee(profile.fees, price, now)
        assert f.fee_rao == RAO_PER_TAO // 10 and f.fee_usd_cents_at_price is None and f.price is None


def test_uid_reuse_never_redirects_reward():
    champ = ChampionState("p1", 3, "5HotkeyChampion", eligible=True, suspended=False)
    # champion deregistered; another hotkey now holds UID 7
    snap = UidSnapshot(500, 99, {"5SomeoneElse": 7, "5Owner": 0}, "5Owner")
    plan = build_weight_plan([champ], {"p1": 10_000}, snap, no_winner_mechanism_verified=False)
    assert all(e.hotkey != "5SomeoneElse" for e in plan.entries)
    assert plan.no_winner and not plan.writer_enabled


def test_eligible_champion_gets_all_miner_weight():
    snap = UidSnapshot(500, 99, {"5Champ": 12, "5Owner": 0}, "5Owner")
    plan = build_weight_plan([ChampionState("p1", 1, "5Champ", True, False)], {"p1": 10_000}, snap, False)
    assert [(e.uid, e.weight_u16, e.role) for e in plan.entries] == [(12, 65535, "champion")]
    assert plan.writer_enabled
