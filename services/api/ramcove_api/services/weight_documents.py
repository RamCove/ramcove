"""The owner's signed weight result, re-issued every tempo for validators to submit (Section 7.5).

The latest weight plan is the owner's evaluation outcome. This module signs a weight document built from
it, valid for two tempos, and replaces it when the plan changes or less than a tempo of validity is left.
Validators fetch it from ``GET /v1/weights/latest``, which serves it only to validators
(``validator_access``); none of them needs to evaluate miners.
"""

from __future__ import annotations

from ramcove_protocol.weight_document import (
    RECORD_TYPE,
    build_weight_document,
    document_hash,
    needs_reissue,
)
from ramcove_protocol.weights import KingSlot
from sqlalchemy import Connection, select
from sqlalchemy.dialects.postgresql import insert

from ..store import audit
from ..store.db import now
from ..store.schema import settings as settings_t
from ..store.schema import weight_plans
from .context import AppContext

SETTING_KEY = "weight_document"


def latest_signed(conn: Connection, ctx: AppContext) -> dict | None:
    return ctx.setting(conn, SETTING_KEY, None)


def ensure_weight_document(conn: Connection, ctx: AppContext, profile_id: str) -> dict | None:
    """Sign a fresh document when one is due. Returns the new signed document, or None if none was due."""
    plan = conn.execute(select(weight_plans).order_by(weight_plans.c.created_at.desc()).limit(1)).first()
    if plan is None:
        return None
    chain = ctx.chain(conn)
    head = chain.finalized_head().number
    current = latest_signed(conn, ctx)
    if not needs_reissue(current["document"] if current else None, plan.id, head):
        return None
    profile = ctx.profile(conn, profile_id)
    doc = build_weight_document(
        [KingSlot(**k) for k in plan.body.get("kings", [])],
        netuid=plan.body["netuid"],
        network=ctx.settings.network,
        genesis_hash=chain.genesis_hash(),
        burn_hotkey=ctx.owner_hotkey,
        issued_block=head,
        plan_id=plan.id,
        rule_hash=profile.rule_hash(),
        champion_version=plan.body["champion_version"],
        weights_version_key=profile.evaluator.weights_version_key,
    )
    signed = {
        "document": doc,
        "document_hash": document_hash(doc),
        "signature": ctx.signer.sign(RECORD_TYPE, doc),
        "signer": ctx.signer.address,
        "scheme": "sr25519",
        "simulated": ctx.settings.simulated_chain,
    }
    conn.execute(
        insert(settings_t)
        .values(key=SETTING_KEY, value=signed, updated_by="controller", reason="weight document issued")
        .on_conflict_do_update(
            index_elements=["key"],
            set_={
                "value": signed,
                "updated_by": "controller",
                "reason": "weight document issued",
                "updated_at": now(),
            },
        )
    )
    if current is None or current["document"].get("plan_id") != plan.id:
        # a new outcome, not a routine renewal: recorded in the public audit log
        audit.append(
            conn,
            "controller",
            "weight_document_issued",
            "weight_plan",
            plan.id,
            {"document_hash": signed["document_hash"], "issued_block": head},
            public=True,
        )
    return signed
