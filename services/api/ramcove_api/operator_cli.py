"""RamCove operator and reviewer command line.

The public site is read-only, so the people who run the network act from here instead, each with their
own key. Every command goes through the same API routes, role checks and audit trail as before.

    ramcove-operator --key-uri URI console
    ramcove-operator --key-uri URI audit-verify
    ramcove-operator --key-uri URI intake pause --reason "..."          # or: intake resume
    ramcove-operator --key-uri URI incident open --severity minor --title "..." --summary "..."
    ramcove-operator --key-uri URI incident resolve inc_...
    ramcove-operator --key-uri URI refund approve ref_...                # or: refund execute
    ramcove-operator --key-uri URI rollback --reason "..." [--deliberate]
    ramcove-operator --key-uri URI reviews
    ramcove-operator --key-uri URI review rev_... approve --reasons "..."
    ramcove-operator --key-uri URI review rev_... reject --failed soak --reasons "..."
    ramcove-operator --key-uri URI appeals
    ramcove-operator --key-uri URI appeal apl_... uphold --reason "..."  # or: dismiss

The key URI form is for local development keys. A production signer is not included in this build, so
``--key-uri`` is refused unless the API reports a simulated network.
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx
from substrateinterface import Keypair

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


def _sign_in(client: httpx.Client, key_uri: str) -> None:
    """Sign in with the hotkey: a message that authorizes no payment."""
    meta = _check(client.get("/v1/meta"))
    if not meta.get("simulated_chain"):
        raise CliError("--key-uri is a development key. Use a wallet signer for a real network.")
    kp = Keypair.create_from_uri(key_uri)
    ch = _check(client.post("/v1/auth/challenge", json={"hotkey": kp.ss58_address}))
    sig = "0x" + kp.sign(ch["message"].encode()).hex()
    _check(client.post("/v1/auth/verify", json={"nonce": ch["nonce"], "signature": sig}))


def _print(doc: dict) -> None:
    print(json.dumps(doc, indent=2, default=str))


def cmd_console(client: httpx.Client, args: argparse.Namespace) -> int:
    c = _check(client.get("/v1/operator/console"))
    intake = c["intake"]
    print(
        f"intake     {'PAUSED' if intake['paused'] else 'open'}  committed {intake['committed_centi']} centi-GPU-h"
    )
    print(
        "states     "
        + (", ".join(f"{k} {v}" for k, v in sorted(c["submissions_by_state"].items())) or "none")
    )
    print("queued     " + (", ".join(f"{k} {v}" for k, v in c["queued_jobs"].items()) or "nothing"))
    for lease in c["leases"]:
        flag = "  EXPIRED" if lease["expired"] else ""
        print(
            f"lease      {lease['job_id']} {lease['stage']} on {lease['worker']} until {lease['expires_at']}{flag}"
        )
    for r in c["open_reviews"]:
        print(
            f"review     {r['id']} for {r['submission_id']} due {r['due_at']}{'  OVERDUE' if r['overdue'] else ''}"
        )
    for i in c["incidents"]:
        if not i["resolved_at"]:
            print(f"incident   {i['id']} [{i['severity']}] {i['title']}")
    for r in c["refunds"]:
        if r["status"] in ("requested", "approved"):
            print(f"refund     {r['id']} {r['status']} {r['amount_rao']} rao to {r['hotkey']}")
    for w in c["workers"]:
        print(
            f"worker     {w['id']} {'ready' if w['ready'] else 'NOT READY'}{'' if w['enabled'] else ' (disabled)'}"
        )
    return 0


def cmd_audit_verify(client: httpx.Client, args: argparse.Namespace) -> int:
    r = _check(client.get("/v1/operator/audit/verify"))
    _print(r)
    return 0 if r.get("ok") else 2


def cmd_intake(client: httpx.Client, args: argparse.Namespace) -> int:
    _print(
        _check(
            client.post("/v1/operator/intake", json={"paused": args.action == "pause", "reason": args.reason})
        )
    )
    return 0


def cmd_incident(client: httpx.Client, args: argparse.Namespace) -> int:
    if args.action == "open":
        if not (args.severity and args.title and args.summary):
            raise CliError("incident open needs --severity, --title and --summary")
        body = {"severity": args.severity, "title": args.title, "public_summary": args.summary}
        _print(_check(client.post("/v1/operator/incidents", json=body)))
    else:
        if not args.id:
            raise CliError("incident resolve needs the incident id")
        _print(_check(client.post(f"/v1/operator/incidents/{args.id}/resolve")))
    return 0


def cmd_refund(client: httpx.Client, args: argparse.Namespace) -> int:
    _print(_check(client.post(f"/v1/operator/refunds/{args.id}/{args.action}")))
    return 0


def cmd_rollback(client: httpx.Client, args: argparse.Namespace) -> int:
    body = {"reason": args.reason, "deliberate": args.deliberate}
    _print(_check(client.post("/v1/operator/champion/rollback", json=body)))
    return 0


def cmd_reviews(client: httpx.Client, args: argparse.Namespace) -> int:
    q = _check(client.get("/v1/review/queue"))
    print("criteria: " + ", ".join(c["id"] for c in q["criteria"]))
    if not q["items"]:
        print("no open reviews")
    for r in q["items"]:
        own = "  (your own: recuse)" if r["is_own_submission"] else ""
        flagged = ", ".join(r.get("flagged") or []) or "none recorded"
        print(
            f"{r['review_id']}  {r['submission_id']}  gain {r['bound_gain_ppm']} ppm  due {r['due_at']}{own}"
            f"\n    flagged: {flagged}"
        )
    return 0


def cmd_review(client: httpx.Client, args: argparse.Namespace) -> int:
    criteria = [c["id"] for c in _check(client.get("/v1/review/queue"))["criteria"]]
    failed = {f.strip() for f in (args.failed or "").split(",") if f.strip()}
    unknown = failed - set(criteria)
    if unknown:
        raise CliError(f"unknown criteria: {', '.join(sorted(unknown))}. Published: {', '.join(criteria)}")
    body = {
        "decision": "approve" if args.action == "approve" else "reject",
        "reasons": args.reasons,
        "criteria": {c: c not in failed for c in criteria},
        "conflict": args.action == "recuse",
    }
    _print(_check(client.post(f"/v1/review/{args.id}/decide", json=body)))
    return 0


def cmd_appeals(client: httpx.Client, args: argparse.Namespace) -> int:
    items = _check(client.get("/v1/appeals"))["items"]
    if not items:
        print("no open appeals")
    for a in items:
        who = "" if a["may_decide"] else "  (you took part: someone else decides)"
        print(f"{a['id']}  {a['submission_id']}  {a['kind']}  due {a['due_at']}{who}\n    {a['grounds']}")
    return 0


def cmd_appeal(client: httpx.Client, args: argparse.Namespace) -> int:
    body = {"upheld": args.action == "uphold", "reason": args.reason}
    _print(_check(client.post(f"/v1/appeals/{args.id}/decide", json=body)))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="ramcove-operator", description="Run the RamCove network: operator and reviewers"
    )
    p.add_argument("--api", default=DEFAULT_API, help=f"API base URL (default {DEFAULT_API})")
    p.add_argument("--key-uri", required=True, help="your own key; its roles decide what you may do")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("console", help="queue health, leases, reviews, incidents, refunds, workers").set_defaults(
        fn=cmd_console
    )
    sub.add_parser("audit-verify", help="check the audit chain end to end").set_defaults(fn=cmd_audit_verify)

    sp = sub.add_parser("intake", help="pause or resume paid admissions")
    sp.add_argument("action", choices=["pause", "resume"])
    sp.add_argument("--reason", required=True)
    sp.set_defaults(fn=cmd_intake)

    sp = sub.add_parser("incident", help="open or resolve a public incident")
    sp.add_argument("action", choices=["open", "resolve"])
    sp.add_argument("id", nargs="?")
    sp.add_argument("--severity", choices=["info", "minor", "major", "critical"])
    sp.add_argument("--title")
    sp.add_argument("--summary", help="what the public status page says")
    sp.set_defaults(fn=cmd_incident)

    sp = sub.add_parser("refund", help="approve, then execute, a refund")
    sp.add_argument("action", choices=["approve", "execute"])
    sp.add_argument("id")
    sp.set_defaults(fn=cmd_refund)

    sp = sub.add_parser("rollback", help="suspend the champion and restore the previous reviewed stack")
    sp.add_argument("--reason", required=True)
    sp.add_argument("--deliberate", action="store_true", help="the champion did something wrong on purpose")
    sp.set_defaults(fn=cmd_rollback)

    sub.add_parser("reviews", help="open promotion reviews and the published criteria").set_defaults(
        fn=cmd_reviews
    )

    sp = sub.add_parser("review", help="decide a promotion review")
    sp.add_argument("id")
    sp.add_argument("action", choices=["approve", "reject", "recuse"])
    sp.add_argument("--failed", help="comma-separated criteria that failed (a rejection needs at least one)")
    sp.add_argument("--reasons", default="", help="the evidence; a rejection must explain it")
    sp.set_defaults(fn=cmd_review)

    sub.add_parser("appeals", help="open appeals").set_defaults(fn=cmd_appeals)

    sp = sub.add_parser("appeal", help="decide an appeal you took no part in")
    sp.add_argument("id")
    sp.add_argument("action", choices=["uphold", "dismiss"])
    sp.add_argument("--reason", required=True)
    sp.set_defaults(fn=cmd_appeal)

    args = p.parse_args(argv)
    try:
        with _api(args.api) as client:
            _sign_in(client, args.key_uri)
            return int(args.fn(client, args))
    except CliError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
