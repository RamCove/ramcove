"""Evaluation stages executed by a worker inside an isolation provider.

With the simulated provider these stages run the protocol's real procedures (task generation, grading,
open-loop schedules, gates, grid readings against the champion's fixed score, quality and memory evidence)
against the coarse ``SimulatedStack`` model. Every result carries ``simulated: true``.

GPU time is accounted in centi-GPU-hours with the planning run lengths of Appendix B: one rate of a reading
(engine start, warm-up, an 8-minute window, drain) is 0.36 h, the short-request control 0.31 h, the multi-turn
run 0.56 h, the soak 1 h. Screening is 10 minutes of GPU time.

Questions come from the owner's question bank for the period (``bank.py``): every evaluation in a period
answers the same screening and quality questions, the champion answers each bank once per worker, and each
capacity reading mixes the bank's traffic with its own drand seed.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict

from ramcove_protocol.canonical import record_hash
from ramcove_protocol.rules import ProfileVersion
from ramcove_protocol.scoring import (
    GateSet,
    PairedQuality,
    QualityEvidence,
    Reading,
    quality_verdict,
    replacement_decision,
)

from .bank import Bank, pack_outcomes, unpack_outcomes
from .capacity import confirmed_capacity, reading_capacity
from .loadgen import CONFIRM_WINDOW_S, CTL_WINDOW_S, SOAK_WINDOW_S, pooled_gates, run_once
from .progress import Reporter, send
from .target import StackParams
from .taskgen import POSITIONS, grade, seed_manifest


class CalibrationMissing(RuntimeError):
    """Infrastructure-side failure: never charged to the miner."""


REFERENCE = StackParams("ramcove-quality-reference-16bit", base_accuracy_bp=9100)
FULL_BUDGET_GIB, TIGHT_BUDGET_GIB = 32.0, 24.0
RUN_CENTI, CTL_CENTI, LIVE_CENTI, SOAK_CENTI = 36, 31, 56, 100  # a reading's rate, P-ctl, P-live, the soak
SCREEN_CENTI = 17  # engine start (at most 5 minutes), 200 questions sent in parallel, memory check
QUALITY_CENTI, CHECK_CENTI = (
    75,
    25,
)  # the challenger answers the bank's 4,000 questions; the GPU check and reset
CHAMPION_ANSWERS_CENTI = (
    75  # the champion answers a bank once per worker, when crowned or when the bank rotates
)
CALIBRATION_CENTI = (
    576  # the champion's fixed score on one worker: search and confirmation, tight budget, P-ctl
)


def _answer(params: StackParams, item, seed: str) -> str | None:
    """Deterministic simulated answer: correct with the stack's group accuracy (item-level, reproducible)."""
    acc = params.base_accuracy_bp - params.accuracy_loss_bp.get(item.group, 0)
    h = int(hashlib.sha256(f"{seed}:{item.item_id}:{params.name}".encode()).hexdigest()[:8], 16) % 10_000
    # shared difficulty term makes stacks agree on most items, as real models do
    shared = int(hashlib.sha256(f"{seed}:{item.item_id}:difficulty".encode()).hexdigest()[:8], 16) % 10_000
    correct = shared < acc if h % 10 else h < acc
    return item.answer if correct else "wrong"


def _outcomes(
    params: StackParams,
    items,
    seed: str,
    on_progress: Reporter | None = None,
    step: str = "questions",
) -> tuple[int, ...]:
    out = []
    for i, item in enumerate(items, 1):
        out.append(int(grade(item, _answer(params, item, seed))))
        if on_progress and (i % 100 == 0 or i == len(items)):
            send(on_progress, step, done=i, total=len(items))
    return tuple(out)


def champion_answers(champion: StackParams, bank: Bank, on_progress: Reporter | None = None) -> dict:
    """The champion's right/wrong per bank question, kept in the worker's calibration record for the period."""
    return {
        "bank_id": bank.bank_id,
        "screening": pack_outcomes(_outcomes(champion, bank.screening, bank.answer_seed)),
        "offline": pack_outcomes(
            _outcomes(champion, bank.offline, bank.answer_seed, on_progress, "champion_answers")
        ),
    }


def _cached_answers(calibration: dict | None, bank: Bank) -> dict | None:
    cached = (calibration or {}).get("answers")
    return cached if cached and cached.get("bank_id") == bank.bank_id else None


def screen(
    params: StackParams,
    champion: StackParams,
    profile: ProfileVersion,
    seed: str,
    bank: Bank,
    calibration: dict | None = None,
    on_progress: Reporter | None = None,
) -> dict:
    checks = []
    if params.screen_failure:
        return {
            "stage": "screen",
            "decisive_failure": params.screen_failure,
            "simulated": True,
            "explanation": {
                "build_failure": "The patch did not build on two clean isolated builds.",
                "no_start": "The engine did not start within 5 minutes.",
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
    items = bank.screening
    cand = sum(_outcomes(params, items, bank.answer_seed, on_progress, "screen_questions"))
    cached = _cached_answers(calibration, bank)
    champ = (
        sum(unpack_outcomes(cached["screening"], len(items)))
        if cached
        else sum(_outcomes(champion, items, bank.answer_seed))
    )
    gap_bp = (champ - cand) * 10_000 // len(items)
    checks.append(f"smoke accuracy: {cand}/{len(items)} (champion {champ}/{len(items)})")
    if gap_bp > 1500:
        return {
            "stage": "screen",
            "decisive_failure": "gross_accuracy",
            "simulated": True,
            "gpu_centi": SCREEN_CENTI,
            "explanation": f"Smoke accuracy is {gap_bp / 100:.1f} points below the champion (decisive limit 15).",
            "checks": checks,
        }
    checks.append("output contract and memory ceiling: ok (speed is not judged here)")
    return {
        "stage": "screen",
        "decisive_failure": None,
        "simulated": True,
        "gpu_centi": SCREEN_CENTI,
        "checks": checks,
    }


def _capacity(params: StackParams, base_rps: float, profile: ProfileVersion, seed: str, budget: float):
    runs: dict[str, object] = {}

    def run(rate: float, label: str) -> bool:
        # the champion's score is confirmed on full 20-minute windows; the search itself uses reading windows
        window = CONFIRM_WINDOW_S if label.startswith("confirm") else None
        logs, g = run_once(
            params,
            f"{seed}:{label}",
            rate,
            profile.latency,
            budget_gib=budget,
            **({"window_s": window} if window else {}),
        )
        runs[f"{label}@{rate:.4f}"] = logs
        return g.passed

    return confirmed_capacity(base_rps, profile.replacement, run), runs


def _fixed_score(champion: StackParams, start_rps: float, profile: ProfileVersion, seed: str, budget: float):
    """The champion's score is recorded once and every challenger is compared with it, so it must not come back
    empty. The grid reaches only about 22% below its starting rate; if nothing confirms, search again from a
    quarter lower, twice at most."""
    for attempt in range(3):
        start = start_rps * 0.75**attempt
        cap, _ = _capacity(champion, start, profile, seed + (f":retry{attempt}" if attempt else ""), budget)
        if cap.capacity_rps:
            break
    return cap


def calibrate(
    champion: StackParams,
    profile: ProfileVersion,
    seed: str,
    base_rps: float,
    bank: Bank,
    on_progress: Reporter | None = None,
) -> dict:
    """The champion's fixed score on this worker: confirmed capacity at the full and the tighter cache budget,
    and its short-request baseline, measured once, when the champion is crowned; plus its answers to the
    current bank, which are refreshed when the bank rotates."""
    seed = f"{bank.traffic_seed}:{seed}"
    send(on_progress, "champion_score", rate_milli_rps=int(base_rps * 1000))
    cap = _fixed_score(champion, base_rps, profile, seed, FULL_BUDGET_GIB)
    send(on_progress, "champion_tight_score", rate_milli_rps=int((cap.capacity_rps or base_rps) * 800))
    # the smaller cache budget can only lower capacity, so search just below the full-budget score
    tight = _fixed_score(
        champion, (cap.capacity_rps or base_rps) * 0.8, profile, seed + ":tight", TIGHT_BUDGET_GIB
    )
    ctl_rate = max(0.2, cap.capacity_rps * 2.0)
    send(on_progress, "short_request", rate_milli_rps=int(ctl_rate * 1000))
    _, ctl = run_once(champion, seed + ":pctl", ctl_rate, profile.latency, ctl=True, window_s=CTL_WINDOW_S)
    return {
        "stage": "calibration",
        "simulated": True,
        "champion": champion.name,
        "capacity_milli_rps": int(cap.capacity_rps * 1000),
        "flag": cap.flag,
        "tight_capacity_milli_rps": int(tight.capacity_rps * 1000),
        "pctl": {
            "rate_milli_rps": int(ctl_rate * 1000),
            "attainment_bp": ctl.attainment_bp,
            "errored_or_rejected": ctl.errored_or_rejected,
        },
        "answers": champion_answers(champion, bank, on_progress),
        "gpu_centi": CALIBRATION_CENTI + CHAMPION_ANSWERS_CENTI,
    }


def _reading(
    params: StackParams,
    base: float,
    profile: ProfileVersion,
    seed: str,
    budget: float,
    on_progress: Reporter | None = None,
    step: str = "reading",
    reading: int = 1,
):
    runs: dict[str, list] = {}

    def run(rate: float, label: str) -> bool:
        send(
            on_progress,
            step,
            reading=reading,
            run=len(runs) + 1,
            rate_milli_rps=int(rate * 1000),
            over_champion_ppm=int(round((rate / base - 1) * 1e6)) if base > 0 else None,
        )
        logs, g = run_once(params, f"{seed}:{label}", rate, profile.latency, budget_gib=budget)
        runs[label] = logs
        return g.passed

    cap = reading_capacity(base, profile.replacement, run)
    return cap, runs


def _reading_record(cap, base: float) -> dict:
    return {
        "challenger_milli_rps": int(cap.capacity_rps * 1000),
        "champion_milli_rps": int(base * 1000),
        "grid_index": cap.index,
        "flag": cap.flag,
        "runs": cap.runs,
        "trace": cap.trace,
    }


def _memory_evidence(
    params: StackParams,
    cap_rps: float,
    profile: ProfileVersion,
    seed: str,
    champion_calibration: dict,
    on_progress: Reporter | None = None,
) -> tuple[dict, int]:
    """Winner check. The challenger's reading under a 25% smaller cache budget, set against the champion's
    fixed score at that budget: the gain must still exceed the replacement margin (ADR 0007). A reading that
    does not clear it gets one more with fresh traffic, because one run failing on noise must not decide a
    winner's fate; either reading may pass. External accounting of resumable idle conversations must also
    improve by the margin, and that probe, not the tighter reading, is what rejects compute-only speedups."""
    tight_base = champion_calibration.get("tight_capacity_milli_rps", 0) / 1000
    delta_ppm = profile.replacement.delta_ppm
    if tight_base <= 0:
        return {"passed": False, "tight_measured": False, "margin_ppm": delta_ppm}, 0
    readings, runs = [], 0
    for n in range(2):
        tight, _ = _reading(
            params,
            tight_base,
            profile,
            f"{seed}:tight{n or ''}",
            TIGHT_BUDGET_GIB,
            on_progress,
            step="memory",
            reading=n + 1,
        )
        runs += tight.runs
        record = _reading_record(tight, tight_base)
        readings.append(
            Reading("tight", 0, record["challenger_milli_rps"], record["champion_milli_rps"], "").gain_ppm()
        )
        if readings[-1] > delta_ppm:
            break
    tight_gain_ppm = max(readings)
    resident_gain = (params.usable_factor / params.kv_factor) * (1 + params.retention_bonus) - 1
    accounting_ok = resident_gain * 1e6 >= delta_ppm
    tight_ok = tight_gain_ppm > delta_ppm
    rate = max(cap_rps * 0.8, 0.1)
    logs, _ = run_once(params, seed + ":acct", rate, profile.latency)
    q = [x for x in logs if x.status == "qualified"]
    recompute = sum(x.recomputed_prefill_tokens for x in logs) / max(1, len(q))
    return {
        "tight_budget_gain_ppm": tight_gain_ppm,
        "tight_readings_ppm": readings,
        "tight_measured": True,
        "tight_ok": tight_ok,
        "margin_ppm": delta_ppm,
        "tight_capacity_milli_rps": {
            "challenger": int(tight_base * (1 + tight_gain_ppm / 1e6) * 1000) if tight_gain_ppm > -1e6 else 0,
            "champion_fixed_score": int(tight_base * 1000),
        },
        "external_resident_capacity_gain_ppm": int(resident_gain * 1e6),
        "recomputed_prefill_tokens_per_qualified": round(recompute),
        "accounting_ok": accounting_ok,
        "passed": tight_ok and accounting_ok,
        "limits": "Diagnostic evidence only; it does not prove that the gain was caused by memory. "
        "Validate the diagnostics against known memory and compute-only methods before trusting them.",
    }, RUN_CENTI * (runs + 1)


def evaluate(
    params: StackParams,
    champion: StackParams,
    profile: ProfileVersion,
    seed: str,
    champion_calibration: dict,
    bank: Bank,
    on_progress: Reporter | None = None,
) -> dict:
    """One evaluation: quality on fresh questions, then one capacity reading against the champion's fixed
    score (a second only when the first lands between the margin and the clear-win line), then, for a winner,
    the memory, short-request, multi-turn and soak checks."""
    base = champion_calibration["capacity_milli_rps"] / 1000
    if base <= 0:
        raise CalibrationMissing("champion calibration has no confirmed capacity; evaluation cannot run")
    items = bank.offline
    cand = _outcomes(params, items, bank.answer_seed, on_progress, "quality")
    cached = _cached_answers(champion_calibration, bank)
    fresh_answers = None if cached else champion_answers(champion, bank, on_progress)
    champ = unpack_outcomes((cached or fresh_answers)["offline"], len(items))
    # the frozen reference's answers ship with the bank: the owner computes them once per period
    ref = _outcomes(REFERENCE, items, bank.answer_seed)
    groups = POSITIONS + ["general"]
    vs_ch, vs_ref, acc = [], [], {}
    for g in ["overall"] + groups:
        idx = [i for i, it in enumerate(items) if g == "overall" or it.group == g]
        vs_ch.append(PairedQuality(g, tuple(cand[i] for i in idx), tuple(champ[i] for i in idx)))
        vs_ref.append(PairedQuality(g, tuple(cand[i] for i in idx), tuple(ref[i] for i in idx)))
        acc[g] = sum(cand[i] for i in idx) * 10_000 // len(idx)
    qv = quality_verdict(QualityEvidence(vs_ch, vs_ref, acc, params.length_ratio_bp), profile.quality)
    gpu = QUALITY_CENTI + CHECK_CENTI + (CHAMPION_ANSWERS_CENTI if fresh_answers else 0)
    result: dict = {
        "stage": "full",
        "simulated": True,
        "seed_manifest": {**seed_manifest(seed, list(items), None, True), "bank_id": bank.bank_id},
        "quality": {
            "passed": qv.passed,
            "reasons": list(qv.reasons),
            "details": qv.details,
            "accuracy_bp": acc,
        },
        "review_flags": [params.review_flag] if params.review_flag else [],
    }
    if fresh_answers:
        result["champion_answers"] = fresh_answers
    seed = f"{bank.traffic_seed}:{seed}"  # the bank's traffic scripts, varied by this evaluation's drand seed
    if not qv.passed:
        result.update(
            winner=False,
            readings=[],
            gpu_centi=gpu,
            summary="Offline quality failed; capacity was not measured. " + "; ".join(qv.reasons)[:400],
            gates=asdict(GateSet(offline_quality=False)),
            failed_gates=["offline_quality"],
        )
        return result
    readings, reading_runs, decision, cap = [], [], None, None
    for n in range(2):
        cap, runs = _reading(
            params, base, profile, f"{seed}:reading{n}", FULL_BUDGET_GIB, on_progress, reading=n + 1
        )
        gpu += RUN_CENTI * cap.runs
        readings.append(_reading_record(cap, base))
        if cap.confirm_label:
            reading_runs.append(runs[cap.confirm_label])
        decision = replacement_decision(
            [
                Reading(f"r{i}", 0, r["challenger_milli_rps"], r["champion_milli_rps"], "")
                for i, r in enumerate(readings)
            ],
            profile.replacement,
            0,
        )
        if decision.outcome != "another_reading":
            break
    gates = GateSet(
        offline_quality=True,
        capacity_reading=cap.index is not None,
        resource_ceilings=not params.exceeds_memory_ceiling,
    )
    winner = decision.outcome == "win"
    extra: dict = {}
    if winner:
        band_ok, band_reasons = pooled_gates(reading_runs, profile.latency)
        mem, mem_gpu = _memory_evidence(
            params, cap.capacity_rps, profile, seed, champion_calibration, on_progress
        )
        base_ctl = champion_calibration.get("pctl") or {}
        ctl_rate = base_ctl.get("rate_milli_rps", int(base * 2000)) / 1000
        send(on_progress, "short_request", rate_milli_rps=int(ctl_rate * 1000))
        _, ctl = run_once(params, seed + ":pctl", ctl_rate, profile.latency, ctl=True, window_s=CTL_WINDOW_S)
        ctl_ok = ctl.attainment_bp >= base_ctl.get("attainment_bp", 0) - 200 and (
            ctl.errored_or_rejected <= base_ctl.get("errored_or_rejected", 0) + 2
        )
        live_rate = max(0.1, cap.capacity_rps * profile.plive_rate_bp / 10_000)
        send(on_progress, "live_conversations", rate_milli_rps=int(live_rate * 1000))
        _, live = run_once(
            params, seed + ":plive", live_rate, profile.latency, live=True, window_s=CONFIRM_WINDOW_S
        )
        send(on_progress, "soak", rate_milli_rps=int(cap.capacity_rps * 900), minutes=int(SOAK_WINDOW_S / 60))
        _, soak = run_once(
            params, seed + ":soak", cap.capacity_rps * 0.9, profile.latency, window_s=SOAK_WINDOW_S
        )
        gpu += mem_gpu + CTL_CENTI + LIVE_CENTI + SOAK_CENTI
        gates = GateSet(
            offline_quality=True,
            capacity_reading=True,
            band_attainment=band_ok,
            memory_evidence=mem["passed"],
            short_request_control=ctl_ok,
            live_conversation_check=live.passed,
            soak=soak.passed,
            resource_ceilings=not params.exceeds_memory_ceiling,
        )
        winner = not gates.failed()
        extra = {
            "band_attainment_reasons": band_reasons,
            "memory_evidence": mem,
            "p_ctl": {
                "passed": ctl_ok,
                "attainment_bp": ctl.attainment_bp,
                "champion_attainment_bp": base_ctl.get("attainment_bp"),
                "rate_milli_rps": int(ctl_rate * 1000),
                "rule": "one run: not more than 2 points below the champion's calibrated short-request result",
            },
            "p_live": {
                "passed": live.passed,
                "offered": live.offered,
                "qualified": live.qualified,
                "conversations_per_s_milli": int(live_rate / 2.57 * 1000),
                "reasons": list(live.reasons),
            },
            "soak": {"passed": soak.passed, "reasons": list(soak.reasons), "load_share_bp": 9000},
        }
    elif cap.index is not None:
        gates = GateSet(
            offline_quality=True, capacity_reading=True, resource_ceilings=not params.exceeds_memory_ceiling
        )
    result.update(extra)
    result.update(
        {
            "readings": readings,
            "decision": {
                "outcome": decision.outcome,
                "gain_ppm": decision.gain_ppm,
                "readings": decision.readings,
                "reasons": list(decision.reasons),
            },
            "gain_ppm": decision.gain_ppm,
            "gates": asdict(gates),
            "failed_gates": gates.failed(),
            "winner": winner,
            "gpu_centi": gpu,
            "summary": _summary(decision, gates, extra, winner),
        }
    )
    return result


def _summary(decision, gates: GateSet, extra: dict, winner: bool) -> str:
    gain = f"{decision.gain_ppm / 1e4:.1f}%" if decision.gain_ppm is not None else "n/a"
    if winner:
        return f"Winner: {gain} over the champion's score, and every winner check passed."
    if decision.outcome != "win":
        return "Not a winner: " + "; ".join(decision.reasons)
    return f"Cleared the margin ({gain}) but a winner check failed: " + _why(gates, extra)


def _why(gates: GateSet, extra: dict) -> str:
    parts = []
    for name in gates.failed():
        if name == "memory_evidence":
            mem = extra.get("memory_evidence", {})
            if not mem.get("tight_measured", True):
                parts.append("memory evidence: the champion has no tighter-budget score on this worker")
            else:
                parts.append(
                    f"memory evidence: gain under a 25% smaller cache budget was "
                    f"{mem['tight_budget_gain_ppm'] / 1e4:.1f}% (needs more than "
                    f"{mem['margin_ppm'] / 1e4:.1f}%), resumable idle capacity "
                    f"{mem['external_resident_capacity_gain_ppm'] / 1e4:.1f}%"
                )
        elif name == "band_attainment":
            parts.append(
                "attainment in a context band fell below 90%: "
                + "; ".join(extra.get("band_attainment_reasons", []))
            )
        elif name == "short_request_control":
            parts.append("short requests regressed against the champion's calibrated result")
        elif name == "live_conversation_check":
            parts.append(
                "multi-turn check with real answers failed: " + "; ".join(extra["p_live"]["reasons"])
            )
        elif name == "soak":
            parts.append(
                "soak at 90% of the measured capacity failed: " + "; ".join(extra["soak"]["reasons"])
            )
        else:
            parts.append(name.replace("_", " "))
    return "; ".join(parts)


def reproduce(
    params: StackParams,
    champion: StackParams,
    profile: ProfileVersion,
    seed: str,
    champion_calibration: dict,
    bank: Bank,
    on_progress: Reporter | None = None,
) -> dict:
    """After the sunset: a second validator repeats one reading against its own worker's fixed score."""
    seed = f"{bank.traffic_seed}:{seed}"
    base = champion_calibration["capacity_milli_rps"] / 1000
    if base <= 0:
        raise CalibrationMissing("champion calibration has no confirmed capacity; reproduction cannot run")
    cap, _ = _reading(params, base, profile, f"{seed}:reproduce", FULL_BUDGET_GIB, on_progress)
    reading = _reading_record(cap, base)
    gain = Reading(
        "reproduce", 0, reading["challenger_milli_rps"], reading["champion_milli_rps"], ""
    ).gain_ppm()
    body = {
        "stage": "reproduce",
        "simulated": True,
        "readings": [reading],
        "gain_ppm": gain,
        "passed": gain > profile.replacement.delta_ppm,
        "gpu_centi": CHECK_CENTI + RUN_CENTI * cap.runs,
    }
    body["report_hash"] = record_hash({k: v for k, v in body.items() if k != "readings"})
    return body
