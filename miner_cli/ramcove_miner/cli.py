"""RamCove miner command line.

    ramcove-miner pack     --patch patch.diff --manifest manifest.json --out artifact.tar.gz
    ramcove-miner preflight --artifact artifact.tar.gz --key-uri //Dev
    ramcove-miner submit   --artifact artifact.tar.gz --key-uri //Dev      # preflight, reserve, quote, pay
    ramcove-miner status   --submission sub_...
    ramcove-miner recover  --block N --index I
    ramcove-miner baseline                                  # the engine pin and settings champion v0 uses
    ramcove-miner champion-code --out champion/             # the champion's patches, to build on

The key URI form is for local development keys. A production signer is not included in this build, so
``--key-uri`` is refused unless the API reports a simulated network.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path

import httpx
from substrateinterface import Keypair

from .artifact import pack, sign_artifact

DEFAULT_API = "http://127.0.0.1:8787"


class CliError(SystemExit):
    pass


def _api(base: str) -> httpx.Client:
    return httpx.Client(base_url=base.rstrip("/"), timeout=60.0, follow_redirects=False)


def _check(r: httpx.Response) -> dict:
    if r.status_code >= 400:
        try:
            err = r.json()["error"]
        except Exception:  # noqa: BLE001
            raise CliError(f"request failed: {r.status_code} {r.text[:200]}") from None
        raise CliError(f"{err.get('code')}: {err.get('message')}")
    return r.json()


def cmd_pack(args: argparse.Namespace) -> int:
    manifest = json.loads(Path(args.manifest).read_text())
    patch = Path(args.patch).read_text()
    data = pack(manifest, patch, Path(args.notice).read_text() if args.notice else None)
    Path(args.out).write_bytes(data)
    print(f"wrote {args.out} ({len(data)} bytes)")
    return 0


def _session(client: httpx.Client, keypair: Keypair, network: str) -> None:
    """Sign in with the hotkey: a message that authorizes no payment."""
    ch = _check(client.post("/v1/auth/challenge", json={"hotkey": keypair.ss58_address}))
    sig = "0x" + keypair.sign(ch["message"].encode()).hex()
    _check(client.post("/v1/auth/verify", json={"nonce": ch["nonce"], "signature": sig}))


def _keypair(uri: str, meta: dict) -> Keypair:
    if not meta.get("simulated_chain"):
        raise CliError("--key-uri is a development key. Use a wallet signer for a real network.")
    return Keypair.create_from_uri(uri)


def cmd_preflight(args: argparse.Namespace) -> int:
    data = Path(args.artifact).read_bytes()
    with _api(args.api) as client:
        meta = _check(client.get("/v1/meta"))
        kp = _keypair(args.key_uri, meta)
        _session(client, kp, meta["network"])
        profile = _check(client.get("/v1/profile"))["profile"]
        sig = sign_artifact(kp, data, meta["network"], profile["profile_id"], profile["version"])
        r = _check(
            client.post(
                "/v1/miner/preflight", files={"file": ("artifact.tar.gz", data)}, data={"signature": sig}
            )
        )
    print(json.dumps(r, indent=2))
    return 0 if r["ok"] else 2


def cmd_submit(args: argparse.Namespace) -> int:
    data = Path(args.artifact).read_bytes()
    with _api(args.api) as client:
        meta = _check(client.get("/v1/meta"))
        kp = _keypair(args.key_uri, meta)
        _session(client, kp, meta["network"])
        profile = _check(client.get("/v1/profile"))["profile"]
        sig = sign_artifact(kp, data, meta["network"], profile["profile_id"], profile["version"])
        pre = _check(
            client.post(
                "/v1/miner/preflight", files={"file": ("artifact.tar.gz", data)}, data={"signature": sig}
            )
        )
        print("free checks:", "passed" if pre["ok"] else "failed")
        for e in pre.get("errors", []):
            print(f"  - {e['code']}: {e['message']}")
        if not pre["ok"]:
            return 2
        sub = pre["submission_id"]
        print(f"submission {sub}")
        res = _check(client.post(f"/v1/miner/submissions/{sub}/reserve", json={}))
        if res["status"] == "waitlisted":
            print(f"waiting list: {res.get('message')}\nNo fee was requested.")
            return 0
        q, d = res["quote"], res["display"]
        print(f"\nQuote {q['quote_id']}")
        print(f"  network   {q['network']}{' (simulated)' if meta['simulated_chain'] else ''}")
        usd = d.get("fee_usd_cents_at_price")
        worth = f"  (about {usd / 100:.2f} USD at the latest price)" if usd is not None else ""
        print(f"  amount    {d['amount_tao']} TAO, a flat fee{worth}")
        print(f"  recipient {q['recipient']}")
        print(f"  expires   block {q['expires_block']}")
        print(f"  note      {q['remark']}")
        print("  the fee is consumed once screening or evaluation runs; operator failures are refunded")
        if args.yes or input("\nPay now? [y/N] ").strip().lower() == "y":
            pay = _check(
                client.post(
                    f"/v1/miner/quotes/{q['quote_id']}/pay-simulated",
                    headers={"idempotency-key": q["quote_id"]},
                )
            )
            print(
                f"payment submitted: block {pay['block_number']} index {pay['extrinsic_index']}"
                f"{' (simulated)' if pay.get('simulated') else ''}"
            )
            print("keep this reference; recovery never charges a second fee")
        else:
            print("not paid. Recover later with: ramcove-miner recover --block N --index I")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    with _api(args.api) as client:
        meta = _check(client.get("/v1/meta"))
        if args.key_uri:
            _session(client, _keypair(args.key_uri, meta), meta["network"])
        r = _check(client.get(f"/v1/submissions/{args.submission}"))
    print(f"{r['submission_id']}  {r['state_label']}")
    if r.get("outcome", {}).get("summary"):
        print(f"  outcome: {r['outcome']['summary']}")
        print(f"  fee: {r['outcome'].get('fee')}")
    for t in r.get("timeline", []):
        print(f"  {t['stage']:<14} {t['status']:<10} {t.get('worker') or ''}")
    return 0


def cmd_recover(args: argparse.Namespace) -> int:
    with _api(args.api) as client:
        meta = _check(client.get("/v1/meta"))
        _session(client, _keypair(args.key_uri, meta), meta["network"])
        r = _check(
            client.post(
                "/v1/miner/payments/recover", json={"block_number": args.block, "extrinsic_index": args.index}
            )
        )
    print(json.dumps(r, indent=2))
    return 0


def cmd_baseline(args: argparse.Namespace) -> int:
    with _api(args.api) as client:
        b = _check(client.get("/v1/baseline"))
    e, m = b["engine"], b["model"]
    print(f"engine   {e['repo']} {e['tag']} at {e['commit']}")
    print(f"model    {m['repo']} at {m['revision']}")
    print(f"paths    {', '.join(e['allowed_paths'])}")
    if b.get("engine_args"):
        print(f"settings {b['engine_args']['status']}")
        for k, v in b["engine_args"]["args"].items():
            print(f"  --{k} {v}")
    print(
        f"champion version {b['current_champion_version']}; patches on top of the baseline: {len(b['champion_stack'])}"
    )
    return 0


def patch_from_artifact(data: bytes, max_bytes: int = 20 * 1024 * 1024) -> str:
    """Read only patch.diff from a champion's artifact, refusing anything but a regular file."""
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        member = tf.getmember("patch.diff")
        if not member.isreg() or member.size > max_bytes:
            raise CliError("the champion's artifact has no readable patch.diff")
        return tf.extractfile(member).read().decode()


def cmd_champion_code(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with _api(args.api) as client:
        b = _check(client.get("/v1/baseline"))
        written = []
        for n, c in enumerate(b["champion_stack"], start=1):
            r = client.get(c["download"])
            if r.status_code != 200:
                raise CliError(f"could not download champion version {c['version']}: {r.status_code}")
            if hashlib.sha256(r.content).hexdigest() != c["artifact_sha256"]:
                raise CliError(f"champion version {c['version']} does not match its published hash")
            path = out / f"{n:02d}-champion-v{c['version']}.diff"
            path.write_text(patch_from_artifact(r.content))
            written.append({**c, "file": path.name})
    (out / "stack.json").write_text(
        json.dumps(
            {"engine": b["engine"], "champion_version": b["current_champion_version"], "patches": written},
            indent=2,
        )
        + "\n"
    )
    if not written:
        print(
            f"champion version {b['current_champion_version']} is the baseline: there are no patches to apply"
        )
    for w in written:
        print(f"wrote {out / w['file']}  (champion v{w['version']}, sha256 {w['artifact_sha256'][:12]}…)")
    print(f"next: baseline/fetch.sh vllm {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ramcove-miner", description="Submit code to the RamCove competition")
    p.add_argument("--api", default=DEFAULT_API, help=f"API base URL (default {DEFAULT_API})")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("pack", help="build a reproducible artifact")
    sp.add_argument("--patch", required=True)
    sp.add_argument("--manifest", required=True)
    sp.add_argument("--notice")
    sp.add_argument("--out", default="artifact.tar.gz")
    sp.set_defaults(fn=cmd_pack)

    sp = sub.add_parser("preflight", help="run the free checks")
    sp.add_argument("--artifact", required=True)
    sp.add_argument("--key-uri", required=True)
    sp.set_defaults(fn=cmd_preflight)

    sp = sub.add_parser("submit", help="free checks, reserve capacity, quote and pay")
    sp.add_argument("--artifact", required=True)
    sp.add_argument("--key-uri", required=True)
    sp.add_argument("--yes", action="store_true", help="do not ask before paying")
    sp.set_defaults(fn=cmd_submit)

    sp = sub.add_parser("status", help="show a submission")
    sp.add_argument("--submission", required=True)
    sp.add_argument("--key-uri")
    sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("recover", help="recover an existing payment by reference")
    sp.add_argument("--block", type=int, required=True)
    sp.add_argument("--index", type=int, required=True)
    sp.add_argument("--key-uri", required=True)
    sp.set_defaults(fn=cmd_recover)

    sp = sub.add_parser("baseline", help="show the engine pin and settings the baseline uses")
    sp.set_defaults(fn=cmd_baseline)

    sp = sub.add_parser("champion-code", help="download the champion's patches to build on")
    sp.add_argument("--out", default="champion")
    sp.set_defaults(fn=cmd_champion_code)

    args = p.parse_args(argv)
    try:
        return int(args.fn(args))
    except CliError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
