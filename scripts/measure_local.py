"""Measure this build on this machine, under a load scenario anyone can repeat.

    uv run python scripts/measure_local.py

Reports the median and 95th percentile for the read endpoints the interface depends on, the
server-rendered pages, and one queue tick. These are local numbers on a developer machine with a
simulated worker; they say nothing about behaviour on real hardware or under real traffic.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request


def _open(url: str):
    """Only http(s) to the local services; ruff's S310 warns about file: and custom schemes."""
    if not url.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise ValueError(f"refusing a non-local URL: {url}")
    return urllib.request.urlopen(url, timeout=30)  # noqa: S310 - scheme and host checked above


API = "http://127.0.0.1:8787"
WEB = "http://127.0.0.1:3787"

API_READS = [
    "/v1/status",
    "/v1/meta",
    "/v1/overview",
    "/v1/profile",
    "/v1/queue",
    "/v1/audit",
    "/v1/appeals",
    "/v1/demo/fixtures",
    "/v1/demo/scenarios",
]
PAGES = ["/", "/competition", "/queue", "/submit", "/validator", "/docs", "/status"]


def timed(url: str, warm: int, runs: int) -> tuple[list[float], int]:
    status = 0
    for _ in range(warm):
        try:
            with _open(url) as r:
                status = r.status
                r.read()
        except urllib.error.HTTPError as e:
            status = e.code
        except OSError:
            return [], 0
    samples = []
    for _ in range(runs):
        t0 = time.perf_counter()
        try:
            with _open(url) as r:
                status = r.status
                r.read()
        except urllib.error.HTTPError as e:
            status = e.code
        except OSError:
            return [], 0
        samples.append((time.perf_counter() - t0) * 1000)
    return samples, status


def report(title: str, base: str, paths: list[str], warm: int, runs: int) -> list[dict]:
    rows = []
    print(f"\n{title}  ({runs} requests each, {warm} warm-up)")
    print(f"  {'path':<26} {'status':>6} {'p50 ms':>9} {'p95 ms':>9} {'max ms':>9}")
    for path in paths:
        samples, status = timed(base + path, warm, runs)
        if not samples:
            print(f"  {path:<26} {'down':>6}")
            continue
        s = sorted(samples)
        p50 = statistics.median(s)
        p95 = s[min(len(s) - 1, int(0.95 * len(s)))]
        rows.append(
            {
                "path": path,
                "status": status,
                "p50_ms": round(p50, 1),
                "p95_ms": round(p95, 1),
                "max_ms": round(max(s), 1),
            }
        )
        print(f"  {path:<26} {status:>6} {p50:>9.1f} {p95:>9.1f} {max(s):>9.1f}")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=30)
    ap.add_argument("--warm", type=int, default=3)
    ap.add_argument("--out", default="var/local-performance.json")
    args = ap.parse_args()

    print("RamCove local performance. Simulated worker, local PostgreSQL, one machine.")
    api = report("API reads", API, API_READS, args.warm, args.runs)
    pages = report("Server-rendered pages", WEB, PAGES, args.warm, max(6, args.runs // 4))

    result = {
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runs_per_endpoint": args.runs,
        "api": api,
        "pages": pages,
        "note": "Local development machine, simulated worker. Not a claim about production.",
    }
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nwrote {args.out}")
    if api:
        print(f"slowest API p95: {max(r['p95_ms'] for r in api):.1f} ms")
    if pages:
        print(f"slowest page p95: {max(r['p95_ms'] for r in pages):.1f} ms")


if __name__ == "__main__":
    main()
