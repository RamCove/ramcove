"""Pure scoring: the replacement decision, quality non-inferiority and gate combination.

Everything here is deterministic and independent of HTTP, databases and chains. Numeric outputs that
enter signed records are converted to integer ppm / basis points by the caller.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .rules import QualityRule, ReplacementRule


@dataclass(frozen=True)
class Reading:
    """One capacity reading of a challenger, set against the champion's fixed score on the same worker."""

    comparison_id: str
    champion_version: int
    challenger_capacity_milli_rps: int
    champion_capacity_milli_rps: int
    worker: str
    voided: bool = False

    def gain_ppm(self) -> int:
        """Integer parts per million (rounded down), so a gain exactly at the margin compares exactly."""
        if self.challenger_capacity_milli_rps <= 0 or self.champion_capacity_milli_rps <= 0:
            return -1_000_000
        return self.challenger_capacity_milli_rps * 1_000_000 // self.champion_capacity_milli_rps - 1_000_000


@dataclass(frozen=True)
class Decision:
    outcome: str  # "win" | "lose" | "another_reading"
    gain_ppm: int | None  # the gain the decision rests on: one reading, or the average of two
    readings: int
    reasons: tuple[str, ...] = field(default_factory=tuple)


def replacement_decision(readings: list[Reading], rule: ReplacementRule, champion_version: int) -> Decision:
    """Section 9.2: at or below the margin loses, at or above the clear-win line wins, in between one more
    reading decides and the average of the two must exceed the margin. Only non-void readings taken against
    *this* champion version count."""
    usable = [r for r in readings if not r.voided and r.champion_version == champion_version]
    reasons: list[str] = []
    stale = [r for r in readings if not r.voided and r.champion_version != champion_version]
    if stale:
        reasons.append(f"{len(stale)} reading(s) against another champion version were ignored")
    if not usable:
        return Decision("another_reading", None, 0, tuple(reasons + ["no usable reading yet"]))
    first = usable[0].gain_ppm()
    if first <= rule.delta_ppm:
        why = (
            "the challenger did not reach the champion's score"
            if first < 0
            else f"gain {first / 1e4:.2f}% does not exceed the {rule.delta_ppm / 1e4:.2f}% margin"
        )
        return Decision("lose", first, 1, tuple(reasons + [why]))
    if first >= rule.clear_win_ppm:
        return Decision("win", first, 1, tuple(reasons))
    if len(usable) < 2:
        return Decision(
            "another_reading",
            first,
            1,
            tuple(reasons + [f"gain {first / 1e4:.2f}% is close to the margin; one more reading decides"]),
        )
    avg = (first + usable[1].gain_ppm()) // 2
    if avg > rule.delta_ppm:
        return Decision("win", avg, 2, tuple(reasons))
    return Decision(
        "lose",
        avg,
        2,
        tuple(reasons + [f"average gain {avg / 1e4:.2f}% over two readings does not exceed the margin"]),
    )


def gain_against_later_champion(gain_ppm: int, promoted_gains_ppm: list[int]) -> int:
    """Re-compare a measured gain with a champion crowned after the measurement, without measuring again.

    Both gains are ratios to the same earlier champion's fixed score, so the challenger's gain over each later
    champion is the ratio of the two: (1 + g) / (1 + g_new) - 1, applied once per promotion in between.
    """
    ratio = 1 + gain_ppm / 1e6
    for g in promoted_gains_ppm:
        ratio /= 1 + g / 1e6
    return int((ratio - 1) * 1e6)


@dataclass(frozen=True)
class PairedQuality:
    """Question-level paired outcomes on the *same* items: 1 correct, 0 wrong (unanswered counts as 0)."""

    group: str
    candidate: tuple[int, ...]
    comparator: tuple[int, ...]


def paired_lower_bound_bp(pq: PairedQuality) -> tuple[int, int]:
    """Return (difference_bp, one-sided 97.5% lower bound bp) for a paired binary comparison.

    SE uses the paired variance of per-item differences, which accounts for discordance.
    """
    if len(pq.candidate) != len(pq.comparator) or not pq.candidate:
        raise ValueError("paired comparison requires equal, non-empty item lists on matching items")
    d = [a - b for a, b in zip(pq.candidate, pq.comparator, strict=True)]
    n = len(d)
    mean = sum(d) / n
    var = sum((x - mean) ** 2 for x in d) / (n - 1) if n > 1 else 0.0
    se = math.sqrt(var / n)
    return round(mean * 10_000), round((mean - 1.96 * se) * 10_000)


def unpaired_lower_bound_bp(
    cand_correct: int, cand_n: int, comp_correct: int, comp_n: int
) -> tuple[int, int]:
    """Two independent proportions (under-load items differ between runs): difference and 97.5% lower bound."""
    if cand_n <= 0 or comp_n <= 0:
        raise ValueError("empty sample")
    p1, p2 = cand_correct / cand_n, comp_correct / comp_n
    se = math.sqrt(p1 * (1 - p1) / cand_n + p2 * (1 - p2) / comp_n)
    return round((p1 - p2) * 10_000), round((p1 - p2 - 1.96 * se) * 10_000)


@dataclass(frozen=True)
class QualityEvidence:
    vs_champion: list[PairedQuality]
    vs_reference: list[PairedQuality]
    candidate_accuracy_bp: dict[str, int]
    candidate_length_ratio_vs_reference_bp: int


@dataclass(frozen=True)
class QualityVerdict:
    passed: bool
    reasons: tuple[str, ...]
    details: dict[str, dict[str, int]]


def quality_verdict(ev: QualityEvidence, rule: QualityRule) -> QualityVerdict:
    """Review R1: must be non-inferior to the champion AND to the frozen reference AND above absolute floors.

    Because the reference and floors never move within a profile version, small permitted losses
    cannot accumulate across generations of champions.
    """
    reasons: list[str] = []
    details: dict[str, dict[str, int]] = {}
    for pq in ev.vs_champion:
        diff, lb = paired_lower_bound_bp(pq)
        details[f"champion:{pq.group}"] = {"diff_bp": diff, "lower_bp": lb}
        limit = -rule.vs_champion_margin_bp if pq.group == "overall" else -rule.vs_champion_stratum_margin_bp
        if lb <= limit:
            reasons.append(
                f"{pq.group}: lower bound {lb / 100:.2f} pts vs champion is not above {limit / 100:.2f}"
            )
    for pq in ev.vs_reference:
        diff, lb = paired_lower_bound_bp(pq)
        details[f"reference:{pq.group}"] = {"diff_bp": diff, "lower_bp": lb}
        if lb <= -rule.vs_reference_margin_bp:
            reasons.append(
                f"{pq.group}: lower bound {lb / 100:.2f} pts vs fixed quality reference is not above "
                f"{-rule.vs_reference_margin_bp / 100:.2f}"
            )
    for group, floor in rule.absolute_min_accuracy_bp.items():
        acc = ev.candidate_accuracy_bp.get(group)
        if acc is None:
            reasons.append(f"{group}: no accuracy measured")
        elif acc < floor:
            reasons.append(
                f"{group}: accuracy {acc / 100:.2f}% is below the absolute floor {floor / 100:.2f}%"
            )
    if ev.candidate_length_ratio_vs_reference_bp < rule.length_ratio_vs_reference_bp:
        reasons.append("output length is below the fixed reference floor")
    return QualityVerdict(not reasons, tuple(reasons), details)


@dataclass(frozen=True)
class GateSet:
    """Pass/fail checks. ``None`` means the check did not run: the winner checks run only for a challenger
    whose readings clear the rule."""

    offline_quality: bool
    capacity_reading: bool | None = None
    band_attainment: bool | None = None
    accuracy_under_load: bool | None = None
    memory_evidence: bool | None = None
    short_request_control: bool | None = None
    live_conversation_check: bool | None = None
    soak: bool | None = None
    resource_ceilings: bool = True

    def failed(self) -> list[str]:
        return [k for k, v in self.__dict__.items() if v is False]
