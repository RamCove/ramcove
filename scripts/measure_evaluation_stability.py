"""How often does one evaluation reject a stack that really is better?

    uv run python scripts/measure_evaluation_stability.py --seeds 8

An evaluation is offline quality, one or two capacity readings against the champion's fixed score, and
winner checks: single runs with pass/fail gates over a noisy measurement. This script runs the real
`evaluate` over several seeds and reports, per fixture, how often it was a winner and which gate stopped it
when it was not.

The number that matters is the rejection rate for a fixture that is genuinely better than the champion: a
miner pays a fee per attempt, so that rate is money lost to noise. Everything here is the simulator, so it
sizes the problem in this build, not on an H100.
"""

from __future__ import annotations

import argparse
import collections
import json

from ramcove_evaluator.bank import build_bank
from ramcove_evaluator.pipeline import calibrate, evaluate
from ramcove_miner.fixtures import FIXTURES, by_name
from ramcove_protocol.rules import ProfileVersion


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--base-rps", type=float, default=0.5)
    ap.add_argument("--only", default="", help="comma-separated fixture names; default is all challengers")
    ap.add_argument("--out", default="var/evaluation-stability.json")
    args = ap.parse_args()

    with open("config/profiles/ramcove-p1@1.0.0.json") as f:
        profile = ProfileVersion.model_validate(json.load(f))
    champion = by_name("champion-v0-tuned")["params"]

    wanted = {n.strip() for n in args.only.split(",") if n.strip()}
    challengers = [
        f
        for f in sorted(FIXTURES, key=lambda f: f["name"])
        if f["role"] == "challenger" and (not wanted or f["name"] in wanted)
    ]

    print(f"Evaluation stability over {args.seeds} seeds. Simulated measurement, not an H100.\n")
    winners: dict[str, int] = collections.defaultdict(int)
    reasons: dict[str, collections.Counter] = {f["name"]: collections.Counter() for f in challengers}
    runs: dict[str, int] = collections.defaultdict(int)

    for i in range(args.seeds):
        # one question bank per seed, as if each seed were a different week
        bank = build_bank(f"measure:{i}", f"measure-bank-{i}", profile.question_bank)
        cal = calibrate(champion, profile, f"calibration:{i}", base_rps=args.base_rps, bank=bank)
        if cal["capacity_milli_rps"] <= 0:
            print(f"  seed {i}: champion calibration did not confirm; skipped", flush=True)
            continue
        for entry in challengers:
            name = entry["name"]
            res = evaluate(entry["params"], champion, profile, f"evaluation:{i}:{name}", cal, bank)
            runs[name] += 1
            if res.get("winner"):
                winners[name] += 1
            else:
                for gate in res.get("failed_gates") or ["margin_not_cleared"]:
                    reasons[name][gate] += 1
        print(f"  seed {i}: done", flush=True)

    print(f"\n  {'fixture':<34} {'winner':>8}   what stopped it")
    rows = []
    for entry in challengers:
        name = entry["name"]
        if not runs[name]:
            continue
        top = ", ".join(f"{g} x{c}" for g, c in reasons[name].most_common(3)) or "-"
        print(f"  {name:<34} {f'{winners[name]}/{runs[name]}':>8}   {top}")
        rows.append(
            {
                "fixture": name,
                "winner": winners[name],
                "runs": runs[name],
                "failed_gates": dict(reasons[name]),
            }
        )

    with open(args.out, "w") as f:
        json.dump({"seeds": args.seeds, "simulated": True, "fixtures": rows}, f, indent=2)
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
