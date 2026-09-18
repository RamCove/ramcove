"""Promotion review and appeals with published criteria, recusal and an independent appeal decider (9.5, R8)."""

from __future__ import annotations

from datetime import timedelta

from ramcove_protocol.state import S
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from ..store import audit
from ..store.db import new_id, now, tx
from ..store.schema import appeals, reviews, role_grants, submissions
from .context import AppContext, ServiceError
from .queue import _consume_fee, review_criteria, transition

APPEAL_WINDOW = timedelta(days=7)
APPEAL_DECISION = timedelta(days=14)


def _has_role(conn, hotkey: str, role: str) -> bool:
    return (
        conn.execute(
            select(role_grants).where(role_grants.c.hotkey == hotkey, role_grants.c.role == role)
        ).first()
        is not None
    )


def decide_review(
    ctx: AppContext,
    review_id: str,
    reviewer: str,
    decision: str,
    reasons: str,
    criteria_results: dict[str, bool],
    conflict: bool,
) -> dict:
    with tx(ctx.engine) as conn:
        rv = conn.execute(select(reviews).where(reviews.c.id == review_id).with_for_update()).first()
        if rv is None:
            raise ServiceError("not_found", "review not found", 404)
        if rv.decision is not None:
            raise ServiceError("already_decided", "this review already has a decision", 409)
        if not _has_role(conn, reviewer, "reviewer"):
            raise ServiceError("forbidden", "reviewer role required", 403)
        sub = conn.execute(
            select(submissions).where(submissions.c.id == rv.submission_id).with_for_update()
        ).first()
        if sub.hotkey == reviewer:
            raise ServiceError("recusal_required", "authors cannot review their own submission", 403)
        if conflict:
            audit.append(
                conn, reviewer, "review_recused", "review", review_id, {"reason": "conflict declared"}
            )
            return {"recused": True, "message": "Conflict recorded; another reviewer must decide."}
        ids = {c["id"] for c in review_criteria()}
        if set(criteria_results) != ids:
            raise ServiceError(
                "criteria_incomplete", "every published criterion needs a pass/fail result", 422
            )
        failed = [k for k, v in criteria_results.items() if not v]
        if decision == "approve" and failed:
            raise ServiceError(
                "inconsistent", f"cannot approve with failed criteria: {', '.join(failed)}", 422
            )
        if decision == "reject" and (not failed or len(reasons.strip()) < 20):
            raise ServiceError(
                "reason_required", "a rejection must cite a failed criterion and explain the evidence", 422
            )
        if sub.state != S.IN_REVIEW:
            raise ServiceError("bad_state", f"submission is {sub.state}", 409)
        criteria = [{**c, "passed": criteria_results[c["id"]]} for c in review_criteria()]
        conn.execute(
            update(reviews)
            .where(reviews.c.id == review_id)
            .values(
                reviewer=reviewer, decision=decision, reasons=reasons, criteria=criteria, decided_at=now()
            )
        )
        if decision == "approve":
            transition(conn, ctx, sub.id, "review_approve", ready_since=now())
        else:
            transition(
                conn,
                ctx,
                sub.id,
                "review_reject",
                fee_outcome="consumed",
                outcome_code="review_rejected",
                outcome_summary=f"Review rejected on: {', '.join(failed)}. {reasons[:300]}",
            )
            _consume_fee(conn, ctx, sub.id)
        audit.append(
            conn,
            reviewer,
            f"review_{decision}",
            "submission",
            sub.id,
            {"review_id": review_id, "failed_criteria": failed},
            public=True,
        )
        return {"decision": decision, "failed_criteria": failed}


def open_appeal(ctx: AppContext, sub_id: str, hotkey: str, grounds: str) -> dict:
    with tx(ctx.engine) as conn:
        sub = conn.execute(select(submissions).where(submissions.c.id == sub_id).with_for_update()).first()
        if sub is None or sub.hotkey != hotkey:
            raise ServiceError("forbidden", "only the author can appeal", 403)
        if sub.state != S.REVIEW_REJECTED:
            raise ServiceError("bad_state", "only rejected reviews can be appealed in this build", 409)
        rv = conn.execute(
            select(reviews)
            .where(reviews.c.submission_id == sub_id, reviews.c.decision == "reject")
            .order_by(reviews.c.decided_at.desc())
        ).first()
        if rv and now() - rv.decided_at > APPEAL_WINDOW:
            raise ServiceError("appeal_window_closed", "the 7-day appeal window has closed", 409)
        if len(grounds.strip()) < 20:
            raise ServiceError("grounds_required", "explain the grounds for the appeal", 422)
        aid = new_id("apl")
        try:
            with conn.begin_nested():
                conn.execute(
                    appeals.insert().values(
                        id=aid,
                        submission_id=sub_id,
                        kind="review",
                        appellant=hotkey,
                        grounds=grounds,
                        disputed_decider=rv.reviewer if rv else None,
                        due_at=now() + APPEAL_DECISION,
                    )
                )
        except IntegrityError as e:
            raise ServiceError("appeal_exists", "an appeal is already open", 409) from e
        audit.append(conn, hotkey, "appeal_opened", "submission", sub_id, {"appeal_id": aid}, public=True)
        return {"appeal_id": aid, "due_at": (now() + APPEAL_DECISION).isoformat()}


def decide_appeal(ctx: AppContext, appeal_id: str, decider: str, upheld: bool, reason: str) -> dict:
    with tx(ctx.engine) as conn:
        ap = conn.execute(select(appeals).where(appeals.c.id == appeal_id).with_for_update()).first()
        if ap is None or ap.status != "open":
            raise ServiceError("not_open", "appeal is not open", 409)
        if not _has_role(conn, decider, "appeal_panel"):
            raise ServiceError("forbidden", "appeal panel role required", 403)
        if decider in (ap.disputed_decider, ap.appellant):
            raise ServiceError(
                "recusal_required", "the disputed decision-maker and the appellant cannot decide", 403
            )
        conn.execute(
            update(appeals)
            .where(appeals.c.id == appeal_id)
            .values(
                status="upheld" if upheld else "dismissed",
                decided_by=decider,
                decision_reason=reason,
                decided_at=now(),
            )
        )
        if upheld:
            from ..store.schema import submissions as subs_t

            sub = conn.execute(
                select(subs_t).where(subs_t.c.id == ap.submission_id).with_for_update()
            ).first()
            transition(
                conn, ctx, sub.id, "appeal_upheld", fee_outcome=None, outcome_code=None, outcome_summary=None
            )
            profile = ctx.profile_by_hash(conn, sub.rule_hash)
            conn.execute(
                reviews.insert().values(
                    id=new_id("rev"),
                    submission_id=sub.id,
                    reviewer="unassigned",
                    criteria=review_criteria(),
                    due_at=now() + timedelta(seconds=profile.deadlines.review_s),
                )
            )
        audit.append(
            conn,
            decider,
            "appeal_" + ("upheld" if upheld else "dismissed"),
            "submission",
            ap.submission_id,
            {"appeal_id": appeal_id},
            public=True,
        )
        return {"status": "upheld" if upheld else "dismissed"}
