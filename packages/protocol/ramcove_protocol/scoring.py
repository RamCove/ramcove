"""Pure scoring: replacement bound, quality non-inferiority and gate combination.

Everything here is deterministic and independent of HTTP, databases and chains. Numeric outputs that
enter signed records are converted to integer ppm / basis points by the caller.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .rules import QualityRule, ReplacementRule

# One-sided 95% Student t quantiles, df = 1..30 (standard table values).
T95 = {
    1: 6.314,
    2: 2.920,
    3: 2.353,
    4: 2.132,
    5: 2.015,
    6: 1.943,
    7: 1.895,
    8: 1.860,
    9: 1.833,
    10: 1.812,
    11: 1.796,
    12: 1.782,
    13: 1.771,
    14: 1.761,
    15: 1.753,
    16: 1.746,
    17: 1.740,
    18: 1.734,
    19: 1.729,
    20: 1.725,
    21: 1.721,
    22: 1.717,
    23: 1.714,
    24: 1.711,
    25: 1.708,
    26: 1.706,
    27: 1.703,
    28: 1.701,
    29: 1.699,
    30: 1.697,
}


@dataclass(frozen=True)
class Block:
    """One paired block: block capacities (single-run grid readings) of both arms on the same fresh tests."""

    comparison_id: str
    champion_version: int
    challenger_capacity_milli_rps: int
    champion_capacity_milli_rps: int
    validator: str
    worker: str
    voided: bool = False


@dataclass(frozen=True)
class BoundResult:
    n: int
    mean_log_ratio: float
    sd_log_ratio: float
    sd_used: float
    lower_log: float
    lower_gain: float
    mean_gain: float
    passes_margin: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)


def replacement_bound(blocks: list[Block], rule: ReplacementRule, champion_version: int) -> BoundResult:
    """Section 8.2 with review R7: only non-void blocks measured against *this* champion version count."""
    usable = [b for b in blocks if not b.voided and b.champion_version == champion_version]
    reasons: list[str] = []
    stale = [b for b in blocks if not b.voided and b.champion_version != champion_version]
    if stale:
        reasons.append(f"{len(stale)} block(s) measured against another champion version were ignored")
    if len(usable) < rule.blocks:
        reasons.append(f"need {rule.blocks} usable blocks, have {len(usable)}")
        return BoundResult(len(usable), 0.0, 0.0, 0.0, -math.inf, -1.0, 0.0, False, tuple(reasons))
    for b in usable:
        if b.challenger_capacity_milli_rps <= 0 or b.champion_capacity_milli_rps <= 0:
            reasons.append("a block has no passing grid rate for one arm; treated as failure")
            return BoundResult(len(usable), 0.0, 0.0, 0.0, -math.inf, -1.0, 0.0, False, tuple(reasons))
    r = [math.log(b.challenger_capacity_milli_rps / b.champion_capacity_milli_rps) for b in usable]
    n = len(r)
    mean = sum(r) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in r) / (n - 1)) if n > 1 else 0.0
    floor = rule.sigma_floor_ppm / 1e6
    sd_used = max(sd, floor)
    t = T95.get(n - 1, 1.645)
    lower = mean - t * sd_used / math.sqrt(n)
    lower_gain = math.exp(lower) - 1
    delta = rule.delta_ppm / 1e6
    passes = lower_gain > delta
    if not passes:
        reasons.append(f"lower bound {lower_gain * 100:.2f}% does not exceed margin {delta * 100:.2f}%")
    return BoundResult(n, mean, sd, sd_used, lower, lower_gain, math.exp(mean) - 1, passes, tuple(reasons))


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
    offline_quality: bool
    per_run_gates: bool
    pooled_gates: bool
    memory_evidence: bool
    short_request_control: bool
    live_conversation_check: bool
    resource_ceilings: bool

    def failed(self) -> list[str]:
        return [k for k, v in self.__dict__.items() if not v]


def triage_is_potential_winner(g_hat_ppm: int, gates: GateSet, rule: ReplacementRule) -> bool:
    return not gates.failed() and g_hat_ppm >= rule.delta_ppm - rule.triage_allowance_ppm
