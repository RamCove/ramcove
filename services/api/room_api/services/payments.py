"""Payment observation: finalized payment -> exactly-once receipt and admission (Section 6.3)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from room_chain.payment import REMARK_PREFIX, Outcome, QuoteTerms, verify_payment
from room_chain.types import Extrinsic
from room_protocol.canonical import record_hash
from room_protocol.state import S
from sqlalchemy import Connection, select, update
from sqlalchemy.dialects.postgresql import insert

from ..store import audit
from ..store.db import new_id, now
from ..store.schema import jobs, payments, quotes, receipts
from ..store.schema import settings as settings_t
from .accounting import issue_credit, ledger_entry, open_refund
from .context import AppContext, ServiceError
from .intake import _set_state, lock_submission


def _quote_id_from(ext: Extrinsic) -> str | None:
    calls = ext.call.inner or (ext.call,)
    for c in calls:
        if (c.module, c.function) == ("System", "remark_with_event"):
            raw = c.args.get("remark")
            data = (
                bytes.fromhex(raw[2:])
                if isinstance(raw, str) and raw.startswith("0x")
                else (raw if isinstance(raw, bytes) else str(raw).encode())
            )
            if data.startswith(REMARK_PREFIX):
                return data[len(REMARK_PREFIX) :].decode(errors="replace")[:40]
    return None


def process_extrinsic(conn: Connection, ctx: AppContext, ext: Extrinsic) -> dict[str, Any] | None:
    quote_id = _quote_id_from(ext)
    if quote_id is None:
        return None
    chain = ctx.chain(conn)
    head = chain.finalized_head()
    existing = conn.execute(
        select(payments).where(
            payments.c.block_hash == ext.block_hash, payments.c.extrinsic_index == ext.index
        )
    ).first()
    if existing is not None:
        return {"outcome": existing.outcome, "reason": existing.reason, "duplicate_observation": True}
    q = conn.execute(select(quotes).where(quotes.c.id == quote_id).with_for_update()).first()
    if q is None:
        return None
    used = {
        (r.payment_block_hash, r.payment_extrinsic_index)
        for r in conn.execute(select(receipts.c.payment_block_hash, receipts.c.payment_extrinsic_index))
    }
    terms = QuoteTerms(q.id, q.payer, q.recipient, q.amount_rao, q.expires_block, q.network)
    verdict = verify_payment(ext, terms, head, chain.block_hash(ext.block_number), used, ctx.settings.network)
    if verdict.outcome == Outcome.NOT_FINALIZED:
        return {"outcome": verdict.outcome.value, "reason": verdict.reason}
    if verdict.outcome == Outcome.VERIFIED and q.status != "open":
        # a second valid-looking payment for a quote that is already paid or expired: money arrived, owe it back
        verdict = type(verdict)(
            Outcome.REJECTED,
            f"quote already {q.status}; duplicate payment",
            verdict.paid_rao,
            0,
            verdict.reference,
            True,
        )
    conn.execute(
        insert(payments)
        .values(
            block_hash=ext.block_hash,
            extrinsic_index=ext.index,
            block_number=ext.block_number,
            network=ctx.settings.network,
            quote_id=q.id,
            payer=ext.signer,
            paid_rao=verdict.paid_rao,
            excess_rao=verdict.excess_rao,
            outcome=verdict.outcome.value,
            reason=verdict.reason,
        )
        .on_conflict_do_nothing(index_elements=["block_hash", "extrinsic_index"])
    )
    ref = f"{ext.block_hash}:{ext.index}"
    sub = lock_submission(conn, q.submission_id)
    if verdict.outcome == Outcome.VERIFIED:
        profile = ctx.profile_by_hash(conn, q.rule_hash)
        if sub.state != S.QUOTED:
            raise ServiceError("bad_state", f"submission {sub.id} is {sub.state}", 409)
        admitted_at = now()
        receipt_id = new_id("rcpt")
        body = {
            "schema": "room.receipt/1",
            "receipt_id": receipt_id,
            "submission_id": sub.id,
            "quote_id": q.id,
            "artifact_sha256": q.artifact_sha256,
            "rule_hash": q.rule_hash,
            "hotkey": q.hotkey,
            "payment": {
                "network": q.network,
                "block_number": ext.block_number,
                "block_hash": ext.block_hash,
                "extrinsic_index": ext.index,
                "paid_rao": verdict.paid_rao,
            },
            "admission_key": [ext.block_number, ext.index],
            "issued_at": admitted_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        conn.execute(
            receipts.insert().values(
                id=receipt_id,
                submission_id=sub.id,
                quote_id=q.id,
                payment_block_hash=ext.block_hash,
                payment_extrinsic_index=ext.index,
                body=body,
                signature=ctx.signer.sign("receipt", body),
                signer=ctx.signer.address,
            )
        )
        conn.execute(update(quotes).where(quotes.c.id == q.id).values(status="paid"))
        _set_state(
            conn,
            sub.id,
            sub.state,
            "payment_verified",
            admission_block=ext.block_number,
            admission_index=ext.index,
            admitted_at=admitted_at,
            deadline_at=admitted_at + timedelta(seconds=profile.deadlines.end_to_end_s),
        )
        ledger_entry(conn, ctx, "fee_received", q.amount_rao, ref, f"fee_received:{ref}", q.hotkey, sub.id)
        if verdict.excess_rao:
            issue_credit(conn, ctx, q.hotkey, verdict.excess_rao, "overpayment", sub.id, f"excess:{ref}")
        conn.execute(
            jobs.insert().values(
                id=new_id("job"),
                submission_id=sub.id,
                profile_id=sub.profile_id,
                stage="screen",
                priority_block=ext.block_number,
                priority_index=ext.index,
                rule_hash=q.rule_hash,
            )
        )
        audit.append(
            conn,
            "system",
            "admitted",
            "submission",
            sub.id,
            {
                "receipt_id": receipt_id,
                "admission_key": [ext.block_number, ext.index],
                "receipt_hash": record_hash(body),
            },
            public=True,
        )
        return {"outcome": "verified", "receipt_id": receipt_id}
    if verdict.outcome == Outcome.LATE:
        conn.execute(
            update(quotes).where(quotes.c.id == q.id, quotes.c.status == "open").values(status="expired")
        )
        if sub.state == S.QUOTED:
            _set_state(
                conn,
                sub.id,
                sub.state,
                "quote_expired",
                reserved_centi=0,
                fee_outcome="refund_or_credit",
                outcome_code="late_payment",
                outcome_summary="Payment finalized after the quote expired.",
            )
    if verdict.refund_eligible and verdict.paid_rao > 0:
        open_refund(
            conn, ctx, q.hotkey, str(ext.signer), verdict.paid_rao, verdict.reason, sub.id, f"refund:{ref}"
        )
    audit.append(
        conn,
        "system",
        "payment_" + verdict.outcome.value,
        "quote",
        q.id,
        {"reason": verdict.reason, "reference": ref},
    )
    return {"outcome": verdict.outcome.value, "reason": verdict.reason}


def scan_finalized(conn: Connection, ctx: AppContext) -> int:
    """Scan newly finalized blocks once, resuming from a durable cursor (safe across restarts)."""
    chain = ctx.chain(conn)
    head = chain.finalized_head()
    key = f"payment_scan_cursor:{ctx.settings.network}"
    cur = conn.execute(select(settings_t).where(settings_t.c.key == key).with_for_update()).first()
    start = int(cur.value["next"]) if cur else 1
    processed = 0
    for n in range(start, head.number + 1):
        for ext in chain.extrinsics(n):
            if process_extrinsic(conn, ctx, ext) is not None:
                processed += 1
    stmt = insert(settings_t).values(
        key=key, value={"next": head.number + 1}, updated_by="controller", reason="payment scan cursor"
    )
    conn.execute(
        stmt.on_conflict_do_update(
            index_elements=["key"], set_={"value": {"next": head.number + 1}, "updated_at": now()}
        )
    )
    return processed


def recover_payment(ctx: AppContext, hotkey: str, block_number: int, extrinsic_index: int) -> dict[str, Any]:
    """Miner-initiated recovery by an existing payment reference: never asks for a second payment."""
    from ..store.db import tx

    with tx(ctx.engine) as conn:
        chain = ctx.chain(conn)
        exts = [e for e in chain.extrinsics(block_number) if e.index == extrinsic_index]
        if not exts:
            raise ServiceError("payment_not_found", "no extrinsic at that block and index", 404)
        qid = _quote_id_from(exts[0])
        q = conn.execute(select(quotes).where(quotes.c.id == qid)).first() if qid else None
        if q is None or q.hotkey != hotkey:
            raise ServiceError(
                "payment_not_yours", "that extrinsic does not reference one of your quotes", 403
            )
        result = process_extrinsic(conn, ctx, exts[0])
        return result or {"outcome": "rejected", "reason": "not a ROOM payment"}


def expire_quotes(conn: Connection, ctx: AppContext) -> int:
    head = ctx.chain(conn).finalized_head()
    n = 0
    for q in conn.execute(
        select(quotes)
        .where(quotes.c.status == "open", quotes.c.expires_block < head.number)
        .with_for_update(skip_locked=True)
    ):
        sub = lock_submission(conn, q.submission_id)
        conn.execute(update(quotes).where(quotes.c.id == q.id).values(status="expired"))
        if sub.state == S.QUOTED:
            _set_state(
                conn,
                sub.id,
                sub.state,
                "quote_expired",
                reserved_centi=0,
                fee_outcome="none",
                outcome_code="quote_expired",
                outcome_summary="The quote expired before a finalized payment was seen. No fee was taken.",
            )
        audit.append(conn, "system", "quote_expired", "quote", q.id, {})
        n += 1
    return n
