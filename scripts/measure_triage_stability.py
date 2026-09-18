"""How often does triage reject a stack that really is better?

    uv run python scripts/measure_triage_stability.py --seeds 8

Triage is a set of single-run pass/fail gates over a noisy measurement. This script runs the real
`full_evaluation` over several seeds and reports, per fixture, how often it was called a potential winner
and which gate stopped it when it was not.

The number that matters is the rejection rate for a fixture that is genuinely better than the champion: a
miner pays a fee per attempt, so that rate is money lost to noise. Everything here is the simulator, so it
sizes the problem in this build, not on an H100.
"""

from __future__ import annotations

import argparse
import collections
import json

from room_evaluator.pipeline import calibrate, full_evaluation
from room_miner.fixtures import FIXTURES, by_name

from room_protocol.rules import ProfileVersion


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--base-rps", type=float, default=0.5)
    ap.add_argument("--only", default="", help="comma-separated fixture names; default is all challengers")
    ap.add_argument("--out", default="var/triage-stability.json")
    args = ap.parse_args()

    with open("config/profiles/room-p1@1.0.0.json") as f:
        profile = ProfileVersion.model_validate(json.load(f))
    champion = by_name("champion-v0-tuned")["params"]

    wanted = {n.strip() for n in args.only.split(",") if n.strip()}
    challengers = [
        f
        for f in sorted(FIXTURES, key=lambda f: f["name"])
        if f["role"] == "challenger" and (not wanted or f["name"] in wanted)
    ]

    print(f"Triage stability over {args.seeds} seeds. Simulated measurement, not an H100.\n")
    winners: dict[str, int] = collections.defaultdict(int)
    reasons: dict[str, collections.Counter] = {f["name"]: collections.Counter() for f in challengers}
    runs: dict[str, int] = collections.defaultdict(int)

    for i in range(args.seeds):
        cal = calibrate(champion, profile, f"calibration:{i}", base_rps=args.base_rps)
        if cal["capacity_milli_rps"] <= 0:
            print(f"  seed {i}: champion calibration did not confirm; skipped", flush=True)
            continue
        for entry in challengers:
            name = entry["name"]
            res = full_evaluation(entry["params"], champion, profile, f"evaluation:{i}:{name}", cal)
            runs[name] += 1
            if res.get("potential_winner"):
                winners[name] += 1
            else:
                for gate, ok in (res.get("gates") or {}).items():
                    if not ok:
                        reasons[name][gate] += 1
        print(f"  seed {i}: done", flush=True)

    print(f"\n  {'fixture':<34} {'potential winner':>17}   gates that failed")
    rows = []
    for entry in challengers:
        name = entry["name"]
        if not runs[name]:
            continue
        top = ", ".join(f"{g} x{c}" for g, c in reasons[name].most_common(3)) or "-"
        print(f"  {name:<34} {f'{winners[name]}/{runs[name]}':>17}   {top}")
        rows.append(
            {
                "fixture": name,
                "potential_winner": winners[name],
                "runs": runs[name],
                "failed_gates": dict(reasons[name]),
            }
        )

    with open(args.out, "w") as f:
        json.dump({"seeds": args.seeds, "simulated": True, "fixtures": rows}, f, indent=2)
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
