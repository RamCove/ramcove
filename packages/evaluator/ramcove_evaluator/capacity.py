"""Capacity measurement procedures with finite grids and defined boundary handling (review R7).

Grid: rate_k = base * (1 + step)^k for integer k in [grid_min_steps, grid_max_steps].

Confirmed capacity (the champion's fixed score, Section 7.8): ascend in coarse jumps of 3 grid steps from
k=0 until a run fails or the ceiling is reached, bisect on grid indices, then confirm with three fresh runs at
the edge minus one step (about 97%), then further steps down (94%, 91%, ... to about 78%); the first level
where all three fresh runs pass is the confirmed capacity. The score is therefore never above a rate proven
three times. Boundary rules:
- no pass at the lowest grid rate -> capacity 0 ("below_grid");
- pass at the highest grid rate -> capacity = ceiling rate, flagged "at_grid_ceiling" (conservative).

Reading (a challenger, Section 7.8): single runs on the grid built on the champion's fixed score. Start at
k=0 and step up while each run passes, at most ``max_runs_per_reading`` runs; the highest passing index is
the reading. A failure at k=0 ends it at once ("below_champion"): the challenger did not reach the score.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ramcove_protocol.rules import ReplacementRule


def grid_rate(base: float, k: int, rule: ReplacementRule) -> float:
    return base * (1 + rule.grid_step_ppm / 1e6) ** k


@dataclass(frozen=True)
class CapacityResult:
    capacity_rps: float
    index: int | None
    flag: str  # ok | below_grid | at_grid_ceiling | not_confirmed
    runs: int
    trace: tuple[tuple[int, bool], ...]
    confirm_label: str | None = None  # label prefix of the runs at the confirmed level (for pooled gates)


RunFn = Callable[[float, str], bool]  # (rate, run_label) -> passed


def confirmed_capacity(
    base: float, rule: ReplacementRule, run: RunFn, confirm_runs: int = 3
) -> CapacityResult:
    lo_k, hi_k = rule.grid_min_steps, rule.grid_max_steps
    trace: list[tuple[int, bool]] = []

    def probe(k: int, label: str) -> bool:
        ok = run(grid_rate(base, k, rule), label)
        trace.append((k, ok))
        return ok

    k = 0
    if not probe(k, "search"):
        # descend coarsely to find any passing rate
        last_fail = 0
        k = -3
        while k >= lo_k and not probe(k, "search"):
            last_fail = k
            k -= 3
        if k < lo_k:
            if not probe(lo_k, "search"):
                return CapacityResult(0.0, None, "below_grid", len(trace), tuple(trace))
            k = lo_k
        good, bad = k, last_fail
    else:
        good = 0
        bad = None
        while True:
            nk = min(good + 3, hi_k)
            if nk == good:
                break
            if probe(nk, "search"):
                good = nk
            else:
                bad = nk
                break
        if bad is None:
            flag_top = True
            edge = good
        else:
            flag_top = False
    if bad is not None:
        while bad - good > 1:
            mid = (good + bad) // 2
            if probe(mid, "search"):
                good = mid
            else:
                bad = mid
        edge = good
        flag_top = False
    for back in range(1, 9):
        ck = max(lo_k, edge - back)
        if all(probe(ck, f"confirm{back}-{i}") for i in range(confirm_runs)):
            flag = "at_grid_ceiling" if flag_top and back == 1 else "ok"
            return CapacityResult(
                grid_rate(base, ck, rule), ck, flag, len(trace), tuple(trace), f"confirm{back}-"
            )
    return CapacityResult(0.0, None, "not_confirmed", len(trace), tuple(trace))


def reading_capacity(base: float, rule: ReplacementRule, run: RunFn) -> CapacityResult:
    hi_k = rule.grid_max_steps
    trace: list[tuple[int, bool]] = []
    best: int | None = None
    best_label: str | None = None
    k = 0
    while len(trace) < rule.max_runs_per_reading and k <= hi_k:
        label = f"reading-run{len(trace)}"
        ok = run(grid_rate(base, k, rule), label)
        trace.append((k, ok))
        if not ok:
            break
        best, best_label = k, label
        k += 1
    if best is None:
        return CapacityResult(0.0, None, "below_champion", len(trace), tuple(trace))
    capped = trace[-1][1]  # still passing when the reading stopped: the true edge may be higher
    flag = "at_grid_ceiling" if capped else "ok"
    return CapacityResult(grid_rate(base, best, rule), best, flag, len(trace), tuple(trace), best_label)
