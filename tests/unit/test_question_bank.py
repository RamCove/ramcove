"""The owner's question bank: periods, seeds and commitments."""

from datetime import UTC, datetime, timedelta

from ramcove_evaluator.bank import build_bank, pack_outcomes, unpack_outcomes
from ramcove_protocol.bank import bank_id, period_index, period_seed, period_window
from ramcove_protocol.rules import QuestionBankRule

RULE = QuestionBankRule()  # 7-day periods from 2026-09-21 00:00 UTC


def test_periods_are_seven_days_from_the_epoch():
    start = datetime(2026, 9, 21, tzinfo=UTC)
    assert period_index(RULE, start) == 0
    assert period_index(RULE, start + timedelta(days=7) - timedelta(seconds=1)) == 0
    assert period_index(RULE, start + timedelta(days=7)) == 1
    assert period_index(RULE, start - timedelta(seconds=1)) == -1
    assert period_window(RULE, 1) == (start + timedelta(days=7), start + timedelta(days=14))


def test_each_period_has_its_own_seed_that_only_the_secret_can_make():
    a = period_seed(b"owner secret", "p1", 0)
    assert a == period_seed(b"owner secret", "p1", 0)
    assert a != period_seed(b"owner secret", "p1", 1)
    assert a != period_seed(b"owner secret", "p2", 0)
    assert a != period_seed(b"another secret", "p1", 0)


def test_a_revealed_seed_rebuilds_the_committed_bank():
    seed = period_seed(b"owner secret", "p1", 0)
    committed = build_bank(bank_id("p1", 0), seed, RULE).commitment()
    rebuilt = build_bank(bank_id("p1", 0), seed, RULE)
    assert rebuilt.commitment() == committed
    assert len(rebuilt.screening) == 200 and len(rebuilt.offline) == 4000
    other = build_bank(bank_id("p1", 1), period_seed(b"owner secret", "p1", 1), RULE)
    assert other.commitment() != committed
    assert {i.item_id for i in other.offline}.isdisjoint({i.item_id for i in rebuilt.offline})


def test_the_champions_answers_pack_small_and_unpack_exactly():
    outcomes = tuple((i * 7) % 3 == 0 for i in range(4000))
    packed = pack_outcomes(tuple(int(x) for x in outcomes))
    assert len(packed) < 700
    assert unpack_outcomes(packed, 4000) == tuple(int(x) for x in outcomes)
