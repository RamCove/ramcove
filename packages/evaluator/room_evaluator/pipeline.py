"""Evaluation stages executed by a worker inside an isolation provider.

With the simulated provider these stages run the protocol's real procedures (task generation, grading,
open-loop schedules, gates, grid search, paired blocks, quality and memory evidence) against the coarse
``SimulatedStack`` model. Every result carries ``simulated: true``.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict

from room_protocol.canonical import record_hash
from room_protocol.rules import ProfileVersion
from room_protocol.scoring import (
    GateSet,
    PairedQuality,
    QualityEvidence,
    quality_verdict,
    triage_is_potential_winner,
)

from .capacity import block_capacity, confirmed_capacity
from .loadgen import pooled_gates, run_once
from .target import StackParams
from .taskgen import POSITIONS, grade, offline_suite, seed_manifest


class CalibrationMissing(RuntimeError):
    """Infrastructure-side failure: never charged to the miner."""


REFERENCE = StackParams("room-quality-reference-16bit", base_accuracy_bp=9100)
OFFLINE_LONG, OFFLINE_GENERAL = 3200, 800  # the profile suite size (Section 7.6)
FULL_BUDGET_GIB, TIGHT_BUDGET_GIB = 32.0, 24.0


def _answer(params: StackParams, item, seed: str) -> str | None:
    """Deterministic simulated answer: correct with the stack's group accuracy (item-level, reproducible)."""
    acc = params.base_accuracy_bp - params.accuracy_loss_bp.get(item.group, 0)
    h = int(hashlib.sha256(f"{seed}:{item.item_id}:{params.name}".encode()).hexdigest()[:8], 16) % 10_000
    # shared difficulty term makes stacks agree on most items, as real models do
    shared = int(hashlib.sha256(f"{seed}:{item.item_id}:difficulty".encode()).hexdigest()[:8], 16) % 10_000
    correct = shared < acc if h % 10 else h < acc
    return item.answer if correct else "wrong"


def _outcomes(params: StackParams, items, seed: str) -> tuple[int, ...]:
    return tuple(int(grade(i, _answer(params, i, seed))) for i in items)


def screen(params: StackParams, champion: StackParams, profile: ProfileVersion, seed: str) -> dict:
    checks = []
    if params.screen_failure:
        return {
            "stage": "screen",
            "decisive_failure": params.screen_failure,
            "simulated": True,
            "explanation": {
                "build_failure": "The patch did not build on two clean isolated builds.",
                "no_start": "The engine did not start within 15 minutes.",
            }.get(params.screen_failure, params.screen_failure),
            "checks": ["isolated build"],
            "gpu_centi": 10,
        }
    checks.append("isolated build: ok")
    if params.exceeds_memory_ceiling:
        return {
            "stage": "screen",
            "decisive_failure": "memory_ceiling",
            "simulated": True,
            "gpu_centi": 20,
            "explanation": "Peak GPU memory exceeded the profile ceiling at low load.",
            "checks": checks,
        }
    items = offline_suite(seed + ":smoke", 150, 50)
    cand = sum(_outcomes(params, items, seed))
    champ = sum(_outcomes(champion, items, seed))
    gap_bp = (champ - cand) * 10_000 // len(items)
    checks.append(f"smoke accuracy: {cand}/{len(items)} (champion {champ}/{len(items)})")
    if gap_bp > 1500:
        return {
            "stage": "screen",
            "decisive_failure": "gross_accuracy",
            "simulated": True,
            "gpu_centi": 35,
            "explanation": f"Smoke accuracy is {gap_bp / 100:.1f} points below the champion (decisive limit 15).",
            "checks": checks,
        }
    checks.append("output contract and memory ceiling: ok (speed is not judged here)")
    return {"stage": "screen", "decisive_failure": None, "simulated": True, "gpu_centi": 35, "checks": checks}


def _capacity(params: StackParams, base_rps: float, profile: ProfileVersion, seed: str, budget: float):
    runs: dict[str, object] = {}

    def run(rate: float, label: str) -> bool:
        logs, g = run_once(params, f"{seed}:{label}", rate, profile.latency, budget_gib=budget)
        runs[f"{label}@{rate:.4f}"] = logs
        return g.passed

    return confirmed_capacity(base_rps, profile.replacement, run), runs


def calibrate(champion: StackParams, profile: ProfileVersion, seed: str, base_rps: float) -> dict:
    cap, _ = _capacity(champion, base_rps, profile, seed, FULL_BUDGET_GIB)
    tight, _ = _capacity(champion, base_rps, profile, seed + ":tight", TIGHT_BUDGET_GIB)
    return {
        "stage": "calibration",
        "simulated": True,
        "champion": champion.name,
        "capacity_milli_rps": int(cap.capacity_rps * 1000),
        "flag": cap.flag,
        "tight_capacity_milli_rps": int(tight.capacity_rps * 1000),
        "gpu_centi": 867,
    }


def _tight_pair(params, champion, tight_base: float, profile: ProfileVersion, seed: str):
    """Measure both arms at the tighter cache budget, retrying once from a lower starting rate.

    The grid only reaches about 22% below its starting rate, so a starting point taken from another job's
    noisy calibration can sit entirely above the real capacity and confirm nothing. One retry an entire
    grid lower costs two searches and removes that failure mode; if it still confirms nothing, the caller
    reports the evidence as not measured rather than as a negative result.
    """
    for attempt, start in enumerate((tight_base, tight_base * 0.75)):
        label = seed + ":tight" + (f":retry{attempt}" if attempt else "")
        tight, _ = _capacity(params, start, profile, label, TIGHT_BUDGET_GIB)
        champ_tight, _ = _capacity(champion, start, profile, label, TIGHT_BUDGET_GIB)
        if tight.capacity_rps and champ_tight.capacity_rps:
            return tight, champ_tight
    return tight, champ_tight


def _memory_evidence(
    params: StackParams,
    champion: StackParams,
    base: float,
    gain: float,
    profile: ProfileVersion,
    seed: str,
    champ_tight_milli: int,
) -> dict:
    # Both tighter-budget capacities are measured fresh in this session with the same procedure, so the
    # comparison is paired; the worker's older champion calibration is reported but not used for the ratio.
    # Search from the champion's tight-budget calibration so both arms start inside the grid.
    tight_base = (champ_tight_milli / 1000) if champ_tight_milli else base * 0.85
    tight, champ_tight = _tight_pair(params, champion, tight_base, profile, seed)
    # A search that confirms nothing is not a measurement, and it is not a -100% result either. The
    # champion's tight calibration comes from a different job with its own noise, so a high reading there
    # can put the whole grid above the real capacity and every level fails. Say "not measured" instead of
    # inventing a catastrophic number, and fail closed on it.
    tight_measured = bool(tight.capacity_rps and champ_tight.capacity_rps)
    tight_gain = (tight.capacity_rps / champ_tight.capacity_rps - 1) if tight_measured else 0.0
    rate = max(base * 0.8, 0.1)
    c_logs, _ = run_once(params, seed + ":acct", rate, profile.latency)
    h_logs, _ = run_once(champion, seed + ":acct", rate, profile.latency)

    def recompute_per_q(logs):
        q = [x for x in logs if x.status == "qualified"]
        return sum(x.recomputed_prefill_tokens for x in logs) / max(1, len(q))

    rc, rh = recompute_per_q(c_logs), recompute_per_q(h_logs)
    # External probe: how many idle conversations can resume without recomputation at the ceiling.
    # Recomputation per qualified request is reported but is NOT sufficient on its own, because it also falls
    # when a stack is simply faster (review R7).
    resident_gain = (params.usable_factor / params.kv_factor) * (1 + params.retention_bonus) - 1
    accounting_ok = resident_gain >= profile.replacement.delta_ppm / 1e6
    # Rule (ADR 0007): under a 25% smaller cache budget the gain must still exceed the replacement margin.
    # The paper's provisional "within 2 points of the full-budget gain" is reported as evidence but is not a
    # gate here, because both capacities are single-run grid readings whose rounding alone can move 2 points.
    delta = profile.replacement.delta_ppm / 1e6
    step = profile.replacement.grid_step_ppm / 1e6
    tolerance = max(profile.replacement.triage_allowance_ppm / 1e6, 2 * step)
    tight_ok = tight_measured and tight_gain >= delta
    holds_within_tolerance = tight_measured and tight_gain >= gain - tolerance
    return {
        "tight_budget_gain_ppm": int(tight_gain * 1e6) if tight_measured else None,
        "tight_measured": tight_measured,
        "tight_ok": tight_ok,
        "tolerance_ppm": int(tolerance * 1e6),
        "full_budget_gain_ppm": int(gain * 1e6),
        "holds_within_tolerance": holds_within_tolerance,
        "margin_ppm": profile.replacement.delta_ppm,
        "tight_flags": {"challenger": tight.flag, "champion": champ_tight.flag},
        "tight_capacity_milli_rps": {
            "challenger": int(tight.capacity_rps * 1000),
            "champion": int(champ_tight.capacity_rps * 1000),
            "worker_calibration_champion": champ_tight_milli,
        },
        "external_resident_capacity_gain_ppm": int(resident_gain * 1e6),
        "recomputed_prefill_tokens_per_qualified": {"challenger": round(rc), "champion": round(rh)},
        "accounting_ok": accounting_ok,
        "recompute_note": "reported only: recomputation also falls for a faster stack, so it cannot by itself "
        "show a memory cause",
        "passed": tight_ok and accounting_ok,
        "limits": "Diagnostic evidence only; it does not prove that the gain was caused by memory. "
        "Validate the diagnostics against known memory and compute-only methods before trusting them.",
    }


def full_evaluation(
    params: StackParams, champion: StackParams, profile: ProfileVersion, seed: str, champion_calibration: dict
) -> dict:
    base = champion_calibration["capacity_milli_rps"] / 1000
    if base <= 0:
        raise CalibrationMissing("champion calibration has no confirmed capacity; triage cannot run")
    items = offline_suite(seed + ":offline", OFFLINE_LONG, OFFLINE_GENERAL)
    cand = _outcomes(params, items, seed)
    champ = _outcomes(champion, items, seed)
    ref = _outcomes(REFERENCE, items, seed)
    groups = POSITIONS + ["general"]
    vs_ch, vs_ref, acc = [], [], {}
    for g in ["overall"] + groups:
        idx = [i for i, it in enumerate(items) if g == "overall" or it.group == g]
        vs_ch.append(PairedQuality(g, tuple(cand[i] for i in idx), tuple(champ[i] for i in idx)))
        vs_ref.append(PairedQuality(g, tuple(cand[i] for i in idx), tuple(ref[i] for i in idx)))
        acc[g] = sum(cand[i] for i in idx) * 10_000 // len(idx)
    qv = quality_verdict(QualityEvidence(vs_ch, vs_ref, acc, params.length_ratio_bp), profile.quality)
    result: dict = {
        "stage": "full",
        "simulated": True,
        "seed_manifest": seed_manifest(seed, items, None, True),
        "quality": {
            "passed": qv.passed,
            "reasons": list(qv.reasons),
            "details": qv.details,
            "accuracy_bp": acc,
        },
    }
    if not qv.passed:
        result.update(
            potential_winner=False,
            gpu_centi=150,
            summary="Offline quality failed; capacity was not measured. " + "; ".join(qv.reasons)[:400],
            gates=asdict(GateSet(False, False, False, False, False, False, True)),
        )
        return result
    cap, runs = _capacity(params, base, profile, seed, FULL_BUDGET_GIB)
    confirmed_runs = [v for k, v in runs.items() if cap.confirm_label and k.startswith(cap.confirm_label)]
    pooled_ok, pooled_reasons = (
        pooled_gates(confirmed_runs, profile.latency) if confirmed_runs else (False, ["no confirmed runs"])
    )
    gain = cap.capacity_rps / base - 1 if base and cap.capacity_rps else -1.0
    mem = _memory_evidence(
        params, champion, base, gain, profile, seed, champion_calibration["tight_capacity_milli_rps"]
    )
    ctl_rate = max(0.2, base * 2.0)
    _, ctl = run_once(params, seed + ":pctl", ctl_rate, profile.latency, ctl=True)
    _, ctl_champ = run_once(champion, seed + ":pctl", ctl_rate, profile.latency, ctl=True)
    ctl_ok = (
        ctl.attainment_bp >= ctl_champ.attainment_bp - 200
        and ctl.errored_or_rejected <= ctl_champ.errored_or_rejected + 2
    )
    live_rate = max(0.1, cap.capacity_rps * profile.plive_rate_bp / 10_000)
    live_logs, live = run_once(params, seed + ":plive", live_rate, profile.latency, live=True)
    gates = GateSet(
        offline_quality=True,
        per_run_gates=cap.flag in ("ok", "at_grid_ceiling"),
        pooled_gates=pooled_ok,
        memory_evidence=mem["passed"],
        short_request_control=ctl_ok,
        live_conversation_check=live.passed,
        resource_ceilings=not params.exceeds_memory_ceiling,
    )
    g_ppm = int(gain * 1e6)
    potential = triage_is_potential_winner(g_ppm, gates, profile.replacement)
    result.update(
        {
            "capacity": {
                "milli_rps": int(cap.capacity_rps * 1000),
                "flag": cap.flag,
                "runs": cap.runs,
                "trace": cap.trace,
                "units": "requests per second, P-mem",
            },
            "pooled_gate_reasons": pooled_reasons,
            "memory_evidence": mem,
            "p_ctl": {
                "passed": ctl_ok,
                "attainment_bp": ctl.attainment_bp,
                "champion_attainment_bp": ctl_champ.attainment_bp,
                "rate_milli_rps": int(ctl_rate * 1000),
                "rule": "paired regression control: not more than 2 points below the champion",
            },
            "p_live": {
                "passed": live.passed,
                "offered": live.offered,
                "qualified": live.qualified,
                "conversations_per_s_milli": int(live_rate / 2.57 * 1000),
                "reasons": list(live.reasons),
            },
            "gates": asdict(gates),
            "failed_gates": gates.failed(),
            "triage_gain_ppm": g_ppm,
            "potential_winner": potential,
            "gpu_centi": 892,
            "summary": (
                "Potential winner: confirmation blocks will be scheduled."
                if potential
                else "Not a potential winner: "
                + (
                    _why(gates, mem, ctl_ok, live, cap)
                    or f"triage gain {g_ppm / 1e4:.1f}% is below the margin minus allowance"
                )
            ),
        }
    )
    return result


def _why(gates, mem: dict, ctl_ok: bool, live, cap) -> str:
    parts = []
    for name in gates.failed():
        if name == "memory_evidence":
            if not mem.get("tight_measured", True):
                parts.append(
                    "memory evidence: capacity under a 25% smaller cache budget could not be confirmed "
                    "for either stack, so the comparison was not measured"
                )
            else:
                parts.append(
                    f"memory evidence: gain under a 25% smaller cache budget was "
                    f"{mem['tight_budget_gain_ppm'] / 1e4:.1f}% (needs more than "
                    f"{mem['margin_ppm'] / 1e4:.1f}%), resumable idle capacity "
                    f"{mem['external_resident_capacity_gain_ppm'] / 1e4:.1f}%"
                )
        elif name == "per_run_gates":
            parts.append(f"capacity could not be confirmed ({cap.flag})")
        elif name == "short_request_control":
            parts.append("short-request control regressed against the champion")
        elif name == "live_conversation_check":
            parts.append("multi-turn check with real answers failed: " + "; ".join(live.reasons))
        else:
            parts.append(name.replace("_", " "))
    return "; ".join(parts)


def confirm_block(
    params: StackParams,
    champion: StackParams,
    profile: ProfileVersion,
    seed: str,
    base_rps: float,
    start_k: int,
) -> dict:
    order = ["challenger", "champion"] if int(seed[:2], 16) % 2 == 0 else ["champion", "challenger"]
    readings = {}
    for arm in order:
        p = params if arm == "challenger" else champion
        k0 = start_k if arm == "challenger" else 0

        def run(rate: float, label: str, _p=p, _arm=arm) -> bool:
            _, g = run_once(_p, f"{seed}:block:{label}", rate, profile.latency)  # same tests for both arms
            return g.passed

        readings[arm] = block_capacity(base_rps, k0, profile.replacement, run)
    body = {
        "stage": "confirm_block",
        "simulated": True,
        "arm_order": order,
        "challenger_milli_rps": int(readings["challenger"].capacity_rps * 1000),
        "champion_milli_rps": int(readings["champion"].capacity_rps * 1000),
        "traces": {a: readings[a].trace for a in readings},
        "gpu_centi": 243,
        "definition": "block capacity: highest grid rate where one 20-minute-equivalent run passes per-run gates",
    }
    body["report_hash"] = record_hash({k: v for k, v in body.items() if k != "traces"})
    return body
