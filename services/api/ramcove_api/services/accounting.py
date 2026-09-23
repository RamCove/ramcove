"""Separated accounting records: fees received/consumed, credits, refund liabilities, refunds.

Every write carries an idempotency key, so replays cannot duplicate credits or refunds.
Token rewards and customer revenue are never recorded here.
"""

from __future__ import annotations

from datetime import timedelta

from ramcove_chain.devchain import DevChain
from ramcove_chain.types import Call
from sqlalchemy import Connection, select, update
from sqlalchemy.dialects.postgresql import insert

from ..store import audit
from ..store.db import new_id, now, tx
from ..store.devchain_sql import SqlDevChainStore
from ..store.schema import credits, ledger, refunds
from .context import AppContext, ServiceError

CREDIT_DAYS = 180


def ledger_entry(
    conn: Connection,
    ctx: AppContext,
    kind: str,
    amount_rao: int,
    reference: str,
    key: str,
    hotkey: str | None = None,
    submission_id: str | None = None,
    memo: str | None = None,
) -> bool:
    res = conn.execute(
        insert(ledger)
        .values(
            kind=kind,
            amount_rao=amount_rao,
            reference=reference,
            idempotency_key=key,
            hotkey=hotkey,
            submission_id=submission_id,
            memo=memo,
            simulated=ctx.settings.simulated_chain,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    return res.rowcount == 1


def issue_credit(
    conn: Connection,
    ctx: AppContext,
    hotkey: str,
    amount_rao: int,
    reason: str,
    submission_id: str | None,
    key: str,
) -> str | None:
    cid = new_id("cr")
    res = conn.execute(
        insert(credits)
        .values(
            id=cid,
            hotkey=hotkey,
            amount_rao=amount_rao,
            reason=reason,
            source_submission=submission_id,
            idempotency_key=key,
            expires_at=now() + timedelta(days=CREDIT_DAYS),
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    if res.rowcount != 1:
        return None
    ledger_entry(conn, ctx, "credit_issued", amount_rao, cid, f"ledger:{key}", hotkey, submission_id, reason)
    audit.append(conn, "system", "credit_issued", "credit", cid, {"amount_rao": amount_rao, "reason": reason})
    return cid


def open_refund(
    conn: Connection,
    ctx: AppContext,
    hotkey: str,
    payer: str,
    amount_rao: int,
    reason: str,
    submission_id: str | None,
    key: str,
) -> str | None:
    rid = new_id("rf")
    res = conn.execute(
        insert(refunds)
        .values(
            id=rid,
            hotkey=hotkey,
            payer=payer,
            amount_rao=amount_rao,
            reason=reason,
            submission_id=submission_id,
            idempotency_key=key,
            simulated=ctx.settings.simulated_chain,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    if res.rowcount != 1:
        return None
    ledger_entry(
        conn, ctx, "refund_liability", amount_rao, rid, f"ledger:{key}", hotkey, submission_id, reason
    )
    audit.append(
        conn, "system", "refund_liability_opened", "refund", rid, {"amount_rao": amount_rao, "reason": reason}
    )
    return rid


def approve_refund(ctx: AppContext, refund_id: str, operator: str) -> dict:
    with tx(ctx.engine) as conn:
        r = conn.execute(select(refunds).where(refunds.c.id == refund_id).with_for_update()).first()
        if r is None:
            raise ServiceError("not_found", "refund not found", 404)
        if r.status != "requested":
            return {"id": r.id, "status": r.status, "idempotent": True}
        conn.execute(
            update(refunds)
            .where(refunds.c.id == refund_id)
            .values(status="approved", approved_by=operator, updated_at=now())
        )
        audit.append(conn, operator, "refund_approved", "refund", refund_id, {"amount_rao": r.amount_rao})
        return {"id": r.id, "status": "approved"}


def execute_refund_demo(ctx: AppContext, refund_id: str, operator: str) -> dict:
    """SIMULATION: send an approved refund on the dev chain. Real refunds require a separately authorized signer."""
    if not ctx.settings.simulated_chain:
        raise ServiceError(
            "disabled", "refund transfers need the authorized signer configured for network mode", 403
        )
    with tx(ctx.engine) as conn:
        r = conn.execute(select(refunds).where(refunds.c.id == refund_id).with_for_update()).first()
        if r is None:
            raise ServiceError("not_found", "refund not found", 404)
        if r.status in ("sent", "confirmed"):
            return {"id": r.id, "status": r.status, "idempotent": True}
        if r.status != "approved":
            raise ServiceError("not_approved", "refund must be approved first", 409)
        chain = DevChain(SqlDevChainStore(conn))
        n = chain.produce_block(
            [
                (
                    ctx.evaluation_wallet,
                    Call("Balances", "transfer_keep_alive", {"dest": r.payer, "value": r.amount_rao}),
                )
            ]
        )
        conn.execute(
            update(refunds)
            .where(refunds.c.id == refund_id)
            .values(status="sent", tx_reference=f"devchain:{n}:0", updated_at=now())
        )
        ledger_entry(
            conn,
            ctx,
            "refund_sent",
            r.amount_rao,
            refund_id,
            f"refund_sent:{refund_id}",
            r.hotkey,
            r.submission_id,
        )
        audit.append(conn, operator, "refund_sent", "refund", refund_id, {"block": n, "simulated": True})
        return {"id": r.id, "status": "sent", "block": n}


def confirm_sent_refunds(conn: Connection, ctx: AppContext) -> int:
    """Mark refunds confirmed once their dev-chain block is finalized and the transfer succeeded."""
    chain = ctx.chain(conn)
    head = chain.finalized_head()
    count = 0
    for r in conn.execute(
        select(refunds).where(refunds.c.status == "sent").with_for_update(skip_locked=True)
    ):
        _, block, idx = r.tx_reference.split(":")
        if int(block) > head.number:
            continue
        ext = [e for e in chain.extrinsics(int(block)) if e.index == int(idx)]
        ok = ext and any(ev.name == "ExtrinsicSuccess" for ev in ext[0].events)
        if ok:
            conn.execute(
                update(refunds).where(refunds.c.id == r.id).values(status="confirmed", updated_at=now())
            )
            ledger_entry(
                conn,
                ctx,
                "refund_confirmed",
                r.amount_rao,
                r.id,
                f"refund_confirmed:{r.id}",
                r.hotkey,
                r.submission_id,
            )
            count += 1
    return count
