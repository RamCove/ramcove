"""Worked examples from the whitepaper (Sections 9.2 and 8.10) and review R1/R7."""

import math

import pytest
from ramcove_protocol.scoring import (
    PairedQuality,
    QualityEvidence,
    Reading,
    gain_against_later_champion,
    paired_lower_bound_bp,
    quality_verdict,
    replacement_decision,
    unpaired_lower_bound_bp,
)


def readings_from_steps(steps, base=100_000, step=1.03, version=0):
    """Each reading is the challenger's highest passing grid rate against the champion's fixed score."""
    return [Reading(f"c{i}", version, round(base * step**k), base, "w1") for i, k in enumerate(steps)]


@pytest.mark.parametrize(
    "steps,outcome,gain_pct,readings",
    [
        ([3], "win", 9.27, 1),  # clear win: one reading at or above 9%
        ([1], "lose", 3.00, 1),  # at or below the 5% margin: one reading decides
        ([0], "lose", 0.00, 1),  # a cosmetic copy scores the champion's own rate
        ([2], "another_reading", 6.09, 1),  # close to the margin: one more reading decides
        ([2, 2], "win", 6.09, 2),  # the average of the two exceeds 5%
        ([2, 1], "lose", 4.55, 2),  # the average of the two does not
    ],
)
def test_paper_examples(profile, steps, outcome, gain_pct, readings):
    d = replacement_decision(readings_from_steps(steps), profile.replacement, champion_version=0)
    assert d.outcome == outcome and d.readings == readings
    assert abs(d.gain_ppm / 1e4 - gain_pct) < 0.01


def test_the_margin_itself_does_not_win(profile):
    exact = [Reading("c0", 0, 105_000, 100_000, "w1")]
    assert replacement_decision(exact, profile.replacement, 0).outcome == "lose"


def test_the_clear_win_line_needs_no_second_reading(profile):
    line = [Reading("c0", 0, 109_000, 100_000, "w1")]
    assert replacement_decision(line, profile.replacement, 0).outcome == "win"


def test_a_lucky_second_reading_cannot_rescue_a_clear_loss(profile):
    d = replacement_decision(readings_from_steps([0, 10]), profile.replacement, 0)
    assert d.outcome == "lose" and d.readings == 1


def test_readings_against_another_champion_are_ignored(profile):
    d = replacement_decision(readings_from_steps([8], version=1), profile.replacement, champion_version=2)
    assert d.outcome == "another_reading" and d.gain_ppm is None
    assert any("another champion version" in x for x in d.reasons)


def test_void_readings_do_not_count(profile):
    rs = [Reading("c0", 0, 200_000, 100_000, "w1", voided=True)]
    assert replacement_decision(rs, profile.replacement, 0).outcome == "another_reading"


def test_no_passing_grid_rate_is_a_loss_not_a_crash(profile):
    rs = [Reading("c0", 0, 0, 100_000, "w1")]
    d = replacement_decision(rs, profile.replacement, 0)
    assert d.outcome == "lose" and "did not reach the champion" in d.reasons[0]


def test_a_measured_winner_is_re_compared_with_a_later_champion_by_arithmetic():
    # measured +12% over v0; v1 is crowned with +6% over v0, so +12% is now +5.66% over v1: still a winner
    assert gain_against_later_champion(120_000, [60_000]) == pytest.approx(56_604, abs=1)
    # v1 crowned with +8% instead: +3.70% over v1, below the margin
    assert gain_against_later_champion(120_000, [80_000]) == pytest.approx(37_037, abs=1)
    # two promotions in between compound
    assert gain_against_later_champion(200_000, [50_000, 50_000]) == pytest.approx(88_435, abs=1)


def test_paired_bound_matches_hand_calculation():
    # 1000 items, candidate wrong on 30 items where comparator right, right on 20 where comparator wrong
    cand = [1] * 950 + [0] * 30 + [1] * 20
    comp = [1] * 950 + [1] * 30 + [0] * 20
    diff, lb = paired_lower_bound_bp(PairedQuality("overall", tuple(cand), tuple(comp)))
    d = [a - b for a, b in zip(cand, comp)]
    mean = sum(d) / len(d)
    sd = math.sqrt(sum((x - mean) ** 2 for x in d) / (len(d) - 1))
    assert diff == -100
    assert lb == round((mean - 1.96 * sd / math.sqrt(len(d))) * 10_000)


def test_paired_requires_matching_items():
    with pytest.raises(ValueError):
        paired_lower_bound_bp(PairedQuality("overall", (1, 1), (1,)))


def test_unpaired_bound_is_wider_than_paired_for_same_rates():
    _, unpaired = unpaired_lower_bound_bp(900, 1000, 900, 1000)
    _, paired = paired_lower_bound_bp(
        PairedQuality("overall", tuple([1] * 900 + [0] * 100), tuple([1] * 900 + [0] * 100))
    )
    assert unpaired < paired == 0


def _generation(acc_prev_bp: int, acc_new_bp: int, n: int = 4000) -> list[int]:
    return [1] * (acc_new_bp * n // 10_000) + [0] * (n - acc_new_bp * n // 10_000)


def test_small_losses_cannot_accumulate_against_fixed_reference(profile):
    """Review R1: 90.0 -> 89.5 -> ... each step passes vs its predecessor but the chain drifts."""
    rule = profile.quality
    reference = _generation(0, 9000)
    acc = 9000
    failed_at = None
    for gen in range(1, 12):
        new_acc = acc - 50
        prev = _generation(0, acc)
        cur = _generation(0, new_acc)
        ev = QualityEvidence(
            vs_champion=[PairedQuality("overall", tuple(cur), tuple(prev))],
            vs_reference=[PairedQuality("overall", tuple(cur), tuple(reference))],
            candidate_accuracy_bp={g: new_acc for g in rule.absolute_min_accuracy_bp},
            candidate_length_ratio_vs_reference_bp=10_000,
        )
        v = quality_verdict(ev, rule)
        champion_only_ok = all("vs champion" not in r for r in v.reasons)
        assert champion_only_ok, "each generation alone is within the champion margin"
        if not v.passed:
            failed_at = gen
            break
        acc = new_acc
    assert failed_at is not None and failed_at <= 8
    assert 9000 - 50 * failed_at <= 9000 - 250


def test_absolute_floor_and_length_floor(profile):
    rule = profile.quality
    same = tuple([1] * 900 + [0] * 100)
    ev = QualityEvidence(
        [PairedQuality("overall", same, same)],
        [PairedQuality("overall", same, same)],
        {
            "overall": 8400,
            "position_early": 9000,
            "position_middle": 9000,
            "position_late": 9000,
            "general": 9000,
        },
        8900,
    )
    v = quality_verdict(ev, rule)
    assert not v.passed
    assert any("absolute floor" in r for r in v.reasons)
    assert any("length" in r for r in v.reasons)
