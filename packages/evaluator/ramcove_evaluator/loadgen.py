"""Open-loop load schedules and per-run / pooled gates.

Units are explicit: P-mem capacity is requests per second (rps). P-live schedules *conversations* per
second: conv_rps = rps / MEAN_TURNS. Offered work counts every scheduled request, including those that
are rejected, time out or never finish before the drain ends.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

from ramcove_protocol.rules import LatencyGates

from .target import RequestLog, StackParams, simulate_run
from .taskgen import BANDS, MEAN_TURNS, conversations


def rps_to_conversations_per_s(rps: float) -> float:
    return rps / MEAN_TURNS


# Run lengths of Appendix B. A reading's rate is judged on an 8-minute window; the champion's confirmation
# runs and P-live use 20 minutes; the short-request control 10; the soak an hour. Bursts last one minute.
READING_WINDOW_S, CONFIRM_WINDOW_S, CTL_WINDOW_S, SOAK_WINDOW_S = 480.0, 1200.0, 600.0, 3600.0
DRAIN_S, BURST_S = 90.0, 60.0


def pmem_schedule(seed: str, rps: float, window_s: float, bursts: bool = True):
    """Prepared-history schedule: turn k at conversation start + earlier 8 s service allowances + think times,
    issued on time even if the previous turn is late (open loop)."""
    conv_rate = rps_to_conversations_per_s(rps)
    r = random.Random(seed + f":{rps:.4f}")
    t = 0.0
    convs = conversations(seed + f":pmem:{rps:.4f}", int(conv_rate * window_s * 2) + 5)
    out = []
    ci = 0
    while t < window_s and ci < len(convs):
        rate = conv_rate * (
            1.5 if bursts and (any(b <= t < b + BURST_S for b in (0.40 * window_s, 0.70 * window_s))) else 1.0
        )
        t += r.expovariate(rate)
        conv = convs[ci]
        ci += 1
        at = t
        for k, item in enumerate(conv.turns):
            if at > window_s:
                break
            out.append((at, item, conv.conv_id, k > 0))
            at += 8.0 + conv.think_s[k] / 10  # think times compressed 10x in the simulated window
    return out


def pctl_schedule(seed: str, rps: float, window_s: float):
    """P-ctl: short single-turn requests (prompt <= 1,500 tokens), a compute-bound regression control."""
    r = random.Random(seed + f":ctl:{rps:.4f}")
    convs = conversations(seed + f":pctl:{rps:.4f}", int(rps * window_s * 1.5) + 5)
    out, t = [], 0.0
    for conv in convs:
        t += r.expovariate(rps)
        if t > window_s:
            break
        it = conv.turns[0]
        out.append(
            (
                t,
                type(it)(
                    it.item_id,
                    it.group,
                    0,
                    min(it.prompt_tokens, 1500),
                    min(it.output_tokens, 200),
                    it.kind,
                    it.answer,
                ),
                conv.conv_id,
                False,
            )
        )
    return out


def plive_schedule(seed: str, rps: float, window_s: float):
    conv_rate = rps_to_conversations_per_s(rps)
    r = random.Random(seed + f":live:{rps:.4f}")
    convs = conversations(seed + f":plive:{rps:.4f}", int(conv_rate * window_s * 2) + 5)
    firsts, live = [], {}
    t = 0.0
    for conv in convs:
        t += r.expovariate(conv_rate)
        if t > window_s:
            break
        firsts.append((t, conv.turns[0], conv.conv_id, False))
        live[conv.conv_id] = (conv.turns[1:], tuple(x / 10 for x in conv.think_s[:-1]))
    return firsts, live


@dataclass(frozen=True)
class RunGates:
    passed: bool
    offered: int
    qualified: int
    errored_or_rejected: int
    attainment_bp: int
    drift_ok: bool
    ceiling_ok: bool
    reasons: tuple[str, ...]


def per_run_gates(logs: list[RequestLog], gates: LatencyGates, ceiling_ok: bool) -> RunGates:
    offered = len(logs)
    if offered == 0:
        return RunGates(False, 0, 0, 0, 0, False, ceiling_ok, ("no offered requests",))
    q = sum(1 for x in logs if x.status == "qualified")
    bad = sum(1 for x in logs if x.status in ("errored", "rejected", "timed_out"))
    att = q * 10_000 // offered
    reasons = []
    if att < gates.attainment_bp:
        reasons.append(f"attainment {att / 100:.1f}% below {gates.attainment_bp / 100:.1f}%")
    if bad * 10_000 > gates.max_error_bp * offered:
        reasons.append(f"{bad} errored/rejected/timed-out requests exceed the limit")
    done = sorted((x for x in logs if x.e2e_ms is not None), key=lambda x: x.scheduled_s)
    drift_ok = True
    if len(done) >= 8:
        # Over-saturation shows as a queue that keeps growing: compare p90 end-to-end time of the last quarter
        # with the second quarter (Section 7.7).
        quarter = len(done) // 4
        q2 = sorted(x.e2e_ms for x in done[quarter : 2 * quarter])
        q4 = sorted(x.e2e_ms for x in done[3 * quarter :])
        p90 = lambda xs: xs[min(len(xs) - 1, int(0.9 * len(xs)))]  # noqa: E731
        drift_ok = p90(q4) * 10_000 <= gates.drift_q4_over_q2_bp * max(1, p90(q2))
        if not drift_ok:
            reasons.append("end-to-end time keeps growing: the queue is not stable")
    if not ceiling_ok:
        reasons.append("GPU memory ceiling exceeded")
    return RunGates(not reasons, offered, q, bad, att, drift_ok, ceiling_ok, tuple(reasons))


def pooled_gates(runs: list[list[RequestLog]], gates: LatencyGates) -> tuple[bool, list[str]]:
    reasons = []
    allogs = [x for r in runs for x in r]
    for b in range(len(BANDS)):
        band = [x for x in allogs if x.band == b]
        if band:
            att = sum(1 for x in band if x.status == "qualified") * 10_000 // len(band)
            if att < gates.band_attainment_bp:
                reasons.append(
                    f"context band {b} attainment {att / 100:.1f}% below {gates.band_attainment_bp / 100:.1f}%"
                )
    return not reasons, reasons


def run_once(
    params: StackParams,
    seed: str,
    rps: float,
    gates: LatencyGates,
    budget_gib: float = 32.0,
    window_s: float = READING_WINDOW_S,
    drain_s: float = DRAIN_S,
    live: bool = False,
    ctl: bool = False,
) -> tuple[list[RequestLog], RunGates]:
    sim_seed = int(
        hashlib.sha256(f"{seed}:{rps:.4f}:{params.name}:{live}:{ctl}".encode()).hexdigest()[:16], 16
    )
    if ctl:
        logs = simulate_run(
            params, pctl_schedule(seed, rps, window_s), window_s, drain_s, budget_gib, gates, sim_seed
        )
    elif live:
        firsts, live_map = plive_schedule(seed, rps, window_s)
        logs = simulate_run(params, firsts, window_s, drain_s, budget_gib, gates, sim_seed, live_map)
    else:
        logs = simulate_run(
            params, pmem_schedule(seed, rps, window_s), window_s, drain_s, budget_gib, gates, sim_seed
        )
    return logs, per_run_gates(logs, gates, ceiling_ok=not params.exceeds_memory_ceiling)
