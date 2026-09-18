"""Worked examples from the whitepaper (Section 8.2, 7.10) and review R1/R7."""

import math

import pytest
from ramcove_protocol.scoring import (
    Block,
    PairedQuality,
    QualityEvidence,
    paired_lower_bound_bp,
    quality_verdict,
    replacement_bound,
    unpaired_lower_bound_bp,
)


def blocks_from_steps(steps, base=100_000, step=1.03, version=0):
    return [Block(f"c{i}", version, round(base * step**k), base, "v1", f"w{i}") for i, k in enumerate(steps)]


@pytest.mark.parametrize(
    "steps,expected_lower_pct,passes",
    [
        ([3, 3, 3, 4, 3], 7.84, True),  # "challenger at 110"
        ([1, 1, 0, 1, 1], 0.46, False),  # "challenger at 103"
        ([3, 3, 2, 3, 3], 6.58, True),  # E vs v0
        ([5, 5, 5, 4, 5], 13.07, True),  # A vs E
        ([0, 0, 1, 0, -1], -1.97, False),  # cosmetic copy
    ],
)
def test_paper_examples_reproduce_within_tolerance(profile, steps, expected_lower_pct, passes):
    r = replacement_bound(blocks_from_steps(steps), profile.replacement, champion_version=0)
    # tolerance: 0.05 percentage points (grid rounding to integer milli-rps)
    assert abs(r.lower_gain * 100 - expected_lower_pct) < 0.05
    assert r.passes_margin is passes


def test_near_tie_keeps_champion(profile):
    r = replacement_bound(blocks_from_steps([2, 2, 2, 2, 2]), profile.replacement, 0)  # +6.1% observed
    assert r.mean_gain > 0.05 and not r.passes_margin


def test_single_lucky_block_cannot_crown(profile):
    r = replacement_bound(blocks_from_steps([10]), profile.replacement, 0)
    assert not r.passes_margin and "need 5 usable blocks" in r.reasons[0]


def test_stale_blocks_against_old_champion_are_ignored(profile):
    old = blocks_from_steps([8, 8, 8, 8, 8], version=1)
    r = replacement_bound(old, profile.replacement, champion_version=2)
    assert not r.passes_margin
    assert any("another champion version" in x for x in r.reasons)


def test_void_blocks_do_not_count(profile):
    bs = blocks_from_steps([4, 4, 4, 4, 4])
    bs[0] = Block("c0", 0, 200_000, 100_000, "v1", "w0", voided=True)
    assert not replacement_bound(bs, profile.replacement, 0).passes_margin


def test_no_passing_grid_rate_is_a_failure_not_a_crash(profile):
    bs = blocks_from_steps([4, 4, 4, 4, 4])
    bs[2] = Block("c2", 0, 0, 100_000, "v1", "w2")
    assert not replacement_bound(bs, profile.replacement, 0).passes_margin


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
