import pytest
from ramcove_protocol.reservation import CapacityPlan, can_admit, remaining_envelope
from ramcove_protocol.settlement import AdmissionKey, QueueEntry, decide_promotion
from ramcove_protocol.state import TERMINAL, TRANSITIONS, S, TransitionError, next_state
from ramcove_protocol.weights import (
    KING_SLOTS,
    U16_MAX,
    KingState,
    UidSnapshot,
    build_weight_plan,
    slot_shares,
)

RH = "rulehash"


def entry(sid, block, state, version=0, registered=True, idx=0):
    return QueueEntry(sid, "p1", AdmissionKey(block, idx), S(state), version, RH, registered)


def test_earlier_job_still_in_full_evaluation_blocks_later_promotion():
    """A was admitted first and is still evaluating; B finished first. B must wait."""
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


def test_admission_is_free_and_follows_the_free_checks_or_an_invitation():
    assert next_state(S.PREFLIGHT_PASSED, "admit") == S.ADMITTED
    assert next_state(S.INVITED, "admit") == S.ADMITTED
    with pytest.raises(TransitionError):
        next_state(S.WAITLISTED, "admit")  # the waiting list is left by invitation, in order
    assert not {"quote", "payment_verified", "quote_expired"} & set(TRANSITIONS)
    assert {s.value for s in S}.isdisjoint({"quoted", "expired_quote"})


def test_booked_work_never_exceeds_the_two_week_queue(profile):
    env = profile.envelope
    plan = CapacityPlan(workers_ready=2, horizon_hours=336)
    committed = 0
    admitted = 0
    for _ in range(1000):  # a flood of submissions
        check = can_admit(committed, env, plan, intake_paused=False)
        if not check.allowed:
            break
        committed += remaining_envelope(S.ADMITTED, env)
        admitted += 1
    # each admission books screening plus one evaluation; the reserve covers winners' extra checks
    assert env.total() == 241
    assert committed <= plan.capacity_centi() < committed + env.total()
    assert admitted == plan.capacity_centi() // env.total() == 223


def test_envelope_releases_as_outcomes_are_known(profile):
    env = profile.envelope
    seq = [S.ADMITTED, S.EVAL_QUEUED, S.IN_REVIEW, S.READY_FOR_PROMOTION, S.PROMOTED]
    values = [remaining_envelope(s, env) for s in seq]
    assert values == [241, 224, 0, 0, 0]


def test_no_admission_when_paused_or_no_safe_workers(profile):
    assert not can_admit(0, profile.envelope, CapacityPlan(2, 336), intake_paused=True).allowed
    assert not can_admit(0, profile.envelope, CapacityPlan(0, 336), intake_paused=False).allowed


def king(slot, hotkey, version=None, eligible=True, profile="p1"):
    return KingState(profile, slot, version if version is not None else 10 - slot, hotkey, eligible)


def by_role(plan):
    return {(e.hotkey, e.role): e.weight_u16 for e in plan.entries}


def test_uid_reuse_never_redirects_reward():
    # King #1 deregistered; another hotkey now holds its old UID 7
    snap = UidSnapshot(500, 99, {"5SomeoneElse": 7, "5Owner": 0}, "5Owner")
    plan = build_weight_plan(
        [king(1, "5HotkeyChampion")], {"p1": 10_000}, snap, no_winner_mechanism_verified=False
    )
    assert all(e.hotkey != "5SomeoneElse" for e in plan.entries)
    assert plan.kings[0].reason == "not_registered" and not plan.kings[0].paid
    assert plan.no_winner and not plan.writer_enabled


def test_no_king_burns_the_whole_miner_allocation():
    snap = UidSnapshot(500, 99, {"5Owner": 0}, "5Owner")
    plan = build_weight_plan([], {"p1": 10_000}, snap, no_winner_mechanism_verified=True)
    assert [(e.uid, e.weight_u16, e.role) for e in plan.entries] == [(0, U16_MAX, "burn")]
    assert plan.no_winner and [k.reason for k in plan.kings] == ["empty"] * 5


def test_the_first_king_earns_the_whole_allocation_and_nothing_burns():
    snap = UidSnapshot(500, 99, {"5King1": 12, "5Owner": 0}, "5Owner")
    plan = build_weight_plan([king(1, "5King1")], {"p1": 10_000}, snap, False)
    assert by_role(plan) == {("5King1", "king"): U16_MAX}
    assert [(k.slot, k.share_bp, k.paid, k.reason) for k in plan.kings] == [
        (1, 10_000, True, "paid"),
        (2, 0, False, "empty"),
        (3, 0, False, "empty"),
        (4, 0, False, "empty"),
        (5, 0, False, "empty"),
    ]
    assert not plan.no_winner and plan.writer_enabled  # nothing burns, so no burn mechanism is needed


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (1, [10_000]),
        (2, [8000, 2000]),
        (3, [6000, 2000, 2000]),
        (4, [4000, 2000, 2000, 2000]),
        (5, [2000, 2000, 2000, 2000, 2000]),
    ],
)
def test_king_one_takes_the_share_of_every_empty_slot(n, expected):
    hotkeys = [f"5King{i}" for i in range(1, n + 1)]
    snap = UidSnapshot(500, 99, {hk: 10 + i for i, hk in enumerate(hotkeys)} | {"5Owner": 0}, "5Owner")
    plan = build_weight_plan(
        [king(i, hk) for i, hk in enumerate(hotkeys, start=1)], {"p1": 10_000}, snap, False
    )
    assert [k.share_bp for k in plan.kings if k.paid] == expected
    assert sum(k.share_bp for k in plan.kings) == 10_000
    assert all(e.role == "king" for e in plan.entries) and plan.writer_enabled


def test_slot_shares_always_add_up_to_the_profile_share():
    for share in (10_000, 6000, 4001, 7):
        for n in range(0, KING_SLOTS + 1):
            shares = slot_shares(share, range(1, n + 1))
            assert sum(shares.values()) == share and list(shares) == [1, 2, 3, 4, 5]
            if n:
                assert all(shares[s] == share // KING_SLOTS for s in range(2, n + 1))


def test_five_kings_share_equally_and_nothing_burns():
    hotkeys = [f"5King{i}" for i in range(1, 6)]
    snap = UidSnapshot(500, 99, {hk: 10 + i for i, hk in enumerate(hotkeys)} | {"5Owner": 0}, "5Owner")
    plan = build_weight_plan(
        [king(i, hk) for i, hk in enumerate(hotkeys, start=1)], {"p1": 10_000}, snap, False
    )
    assert {e.hotkey: e.weight_u16 for e in plan.entries} == {hk: U16_MAX // 5 for hk in hotkeys}
    assert all(e.role == "king" for e in plan.entries) and plan.writer_enabled


def test_an_ineligible_king_keeps_its_place_and_its_share_burns():
    snap = UidSnapshot(500, 99, {"5King1": 12, "5King2": 13, "5King3": 14, "5Owner": 0}, "5Owner")
    kings = [king(1, "5King1"), king(2, "5King2", eligible=False), king(3, "5King3")]
    plan = build_weight_plan(kings, {"p1": 10_000}, snap, True)
    assert [(k.slot, k.hotkey, k.reason) for k in plan.kings[:3]] == [
        (1, "5King1", "paid"),
        (2, "5King2", "ineligible"),
        (3, "5King3", "paid"),
    ]
    # King #1 holds its own 20% and the two empty slots' 40%; only the ineligible king's 20% burns
    assert by_role(plan) == {
        ("5King1", "king"): 6000 * U16_MAX // 10_000,
        ("5King3", "king"): 2000 * U16_MAX // 10_000,
        ("5Owner", "burn"): 2000 * U16_MAX // 10_000,
    }


def test_one_hotkey_holding_two_slots_earns_both():
    snap = UidSnapshot(500, 99, {"5Twice": 12, "5Other": 13, "5Owner": 0}, "5Owner")
    plan = build_weight_plan(
        [king(1, "5Twice"), king(2, "5Other"), king(3, "5Twice")], {"p1": 10_000}, snap, True
    )
    assert by_role(plan)[("5Twice", "king")] == 8000 * U16_MAX // 10_000  # King #1's 60% and slot 3's 20%


def test_each_profile_pays_its_own_kings_from_its_own_share():
    snap = UidSnapshot(500, 99, {"5A": 12, "5B": 13, "5Owner": 0}, "5Owner")
    plan = build_weight_plan(
        [king(1, "5A", profile="p1"), king(1, "5B", profile="p2")], {"p1": 6000, "p2": 4000}, snap, True
    )
    assert by_role(plan) == {
        ("5A", "king"): 6000 * U16_MAX // 10_000,
        ("5B", "king"): 4000 * U16_MAX // 10_000,
    }


def test_slots_are_checked():
    snap = UidSnapshot(500, 99, {"5A": 12, "5Owner": 0}, "5Owner")
    with pytest.raises(ValueError):
        build_weight_plan([king(6, "5A")], {"p1": 10_000}, snap, True)
    with pytest.raises(ValueError):
        build_weight_plan([king(1, "5A"), king(1, "5A")], {"p1": 10_000}, snap, True)
