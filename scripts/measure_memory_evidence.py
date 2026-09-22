"""How stable is the memory-evidence decision across random seeds?

    uv run python scripts/measure_memory_evidence.py --seeds 6

ADR 0007 decides "is this a memory method?" by asking whether the gain survives a 25% smaller cache
budget by more than the margin. That decision is measured, so it carries noise. This script runs each
demonstration fixture under several seeds and reports how often it is called a memory method, together
with the spread of the tight-budget gain.

A fixture that lands near the margin will flip between runs. Finding one is the point: it tells you the
margin is not yet separated from the noise, which is what Stage 1 calibration on real hardware must fix.
Everything here runs against the simulator, so the numbers describe the simulation, not an H100.
"""

from __future__ import annotations

import argparse
import json
import statistics

from ramcove_evaluator.bank import build_bank
from ramcove_evaluator.pipeline import (
    FULL_BUDGET_GIB,
    TIGHT_BUDGET_GIB,
    _memory_evidence,
    _reading,
    calibrate,
)
from ramcove_miner.fixtures import FIXTURES, by_name
from ramcove_protocol.rules import ProfileVersion


def load_profile() -> ProfileVersion:
    with open("config/profiles/ramcove-p1@1.0.0.json") as f:
        return ProfileVersion.model_validate(json.load(f))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=6)
    # the starting rate the worker uses in services/worker/ramcove_worker/runner.py
    ap.add_argument("--base-rps", type=float, default=0.5)
    ap.add_argument("--out", default="var/memory-evidence.json")
    args = ap.parse_args()

    profile = load_profile()
    champion = by_name("champion-v0-tuned")["params"]
    margin_pct = profile.replacement.delta_ppm / 1e4

    print(f"Memory-evidence stability, {args.seeds} seeds per fixture, margin {margin_pct:.1f}%")
    print("Simulated serving model. Not a measurement of any GPU.\n")

    # Reproduce exactly what the worker does: record the champion's fixed score, take the challenger's
    # reading against it, then ask the pipeline's own _memory_evidence with the arguments evaluate passes.
    challengers = [f for f in sorted(FIXTURES, key=lambda f: f["name"]) if f["role"] == "challenger"]
    gains: dict[str, list[float]] = {f["name"]: [] for f in challengers}
    passes: dict[str, list[bool]] = {f["name"]: [] for f in challengers}
    unmeasured: dict[str, int] = {f["name"]: 0 for f in challengers}

    for i in range(args.seeds):
        # The real system calibrates the champion in one job and evaluates a challenger in another, so
        # the two carry independent noise. Using one seed for both hides exactly that effect.
        bank = build_bank(f"measure:{i}", f"measure-bank-{i}", profile.question_bank)
        cal = calibrate(champion, profile, f"calibration:{i}", base_rps=args.base_rps, bank=bank)
        seed = f"evaluation:{i}"
        base = cal["capacity_milli_rps"] / 1000
        if base <= 0:
            print(f"  seed {i}: champion calibration did not confirm; skipped", flush=True)
            continue
        for entry in challengers:
            params = entry["params"]
            cap, _ = _reading(params, base, profile, f"{seed}:reading0", FULL_BUDGET_GIB)
            mem, _ = _memory_evidence(params, cap.capacity_rps, profile, seed, cal)
            # the champion's tighter-budget score was missing: counted separately, not as a number
            if not mem.get("tight_measured"):
                unmeasured[entry["name"]] += 1
            else:
                gains[entry["name"]].append(mem["tight_budget_gain_ppm"] / 1e4)
            passes[entry["name"]].append(bool(mem["passed"]))
        print(f"  seed {i}: done", flush=True)

    print()
    print(f"  {'fixture':<34} {'calls it memory':>16} {'tight gain % (min..max)':>26}")
    rows = []
    for entry in challengers:
        name = entry["name"]
        g, verdicts = gains[name], passes[name]
        if not verdicts:
            continue
        if not g:
            print(f"  {name:<34} {f'0/{len(verdicts)}':>16} {'never confirmed':>26}")
            rows.append(
                {
                    "fixture": name,
                    "declared_memory": 0,
                    "seeds": len(verdicts),
                    "unmeasured": unmeasured[name],
                    "stable": True,
                }
            )
            continue
        rate = sum(verdicts) / len(verdicts)
        flag = "  <- flips" if 0 < rate < 1 else ""
        note = f" ({unmeasured[name]} not measured)" if unmeasured[name] else ""
        print(
            f"  {name:<34} {f'{sum(verdicts)}/{len(verdicts)}':>16} "
            f"{f'{min(g):.1f} .. {max(g):.1f}':>26}{flag}{note}"
        )
        rows.append(
            {
                "fixture": name,
                "declared_memory": sum(verdicts),
                "seeds": len(verdicts),
                "tight_gain_pct_min": round(min(g), 2),
                "tight_gain_pct_max": round(max(g), 2),
                "tight_gain_pct_median": round(statistics.median(g), 2),
                "unmeasured": unmeasured[name],
                "stable": rate in (0.0, 1.0),
            }
        )

    with open(args.out, "w") as f:
        json.dump(
            {
                "margin_pct": margin_pct,
                "budget_gib": {"full": FULL_BUDGET_GIB, "tight": TIGHT_BUDGET_GIB},
                "simulated": True,
                "fixtures": rows,
            },
            f,
            indent=2,
        )
    unstable = [r["fixture"] for r in rows if not r["stable"]]
    print(f"\nwrote {args.out}")
    print(f"unstable across seeds: {', '.join(unstable) if unstable else 'none'}")


if __name__ == "__main__":
    main()
