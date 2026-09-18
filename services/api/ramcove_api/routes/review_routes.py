"""Reviewer and appeal-panel routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..services import review
from ..services.context import AppContext
from ..services.queue import review_criteria
from ..store.db import tx
from ..store.schema import appeals, reviews, submissions
from .deps import get_ctx, require_role

router = APIRouter(prefix="/v1", tags=["review"])


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    reasons: str = Field("", max_length=4000)
    criteria: dict[str, bool]
    conflict: bool = False


class AppealDecisionIn(BaseModel):
    upheld: bool
    reason: str = Field(min_length=10, max_length=4000)


@router.get("/review/queue")
def queue(
    ctx: AppContext = Depends(get_ctx), sess: dict = Depends(require_role("reviewer", "operator"))
) -> dict:
    with tx(ctx.engine) as conn:
        open_reviews = conn.execute(
            select(
                reviews,
                submissions.c.hotkey,
                submissions.c.lineage,
                submissions.c.bound_gain_ppm,
                submissions.c.triage_gain_ppm,
            )
            .join(submissions, submissions.c.id == reviews.c.submission_id)
            .where(reviews.c.decision.is_(None))
            .order_by(reviews.c.opened_at)
        ).all()
        return {
            "criteria": review_criteria(),
            "items": [
                {
                    "review_id": r.id,
                    "submission_id": r.submission_id,
                    "author": r.hotkey,
                    "lineage": r.lineage,
                    "bound_gain_ppm": r.bound_gain_ppm,
                    "triage_gain_ppm": r.triage_gain_ppm,
                    "opened_at": r.opened_at,
                    "due_at": r.due_at,
                    "is_own_submission": r.hotkey == sess["hotkey"],
                }
                for r in open_reviews
            ],
        }


@router.post("/review/{review_id}/decide")
def decide(
    review_id: str,
    body: DecisionIn,
    ctx: AppContext = Depends(get_ctx),
    sess: dict = Depends(require_role("reviewer")),
) -> dict:
    return review.decide_review(
        ctx, review_id, sess["hotkey"], body.decision, body.reasons, body.criteria, body.conflict
    )


@router.get("/appeals")
def list_appeals(
    ctx: AppContext = Depends(get_ctx), sess: dict = Depends(require_role("appeal_panel", "operator"))
) -> dict:
    with tx(ctx.engine) as conn:
        rows = conn.execute(
            select(appeals).where(appeals.c.status == "open").order_by(appeals.c.opened_at)
        ).all()
        return {
            "items": [
                {
                    "id": a.id,
                    "submission_id": a.submission_id,
                    "kind": a.kind,
                    "grounds": a.grounds,
                    "appellant": a.appellant,
                    "disputed_decider": a.disputed_decider,
                    "due_at": a.due_at,
                    "may_decide": sess["hotkey"] not in (a.disputed_decider, a.appellant),
                }
                for a in rows
            ]
        }


@router.post("/appeals/{appeal_id}/decide")
def decide_appeal(
    appeal_id: str,
    body: AppealDecisionIn,
    ctx: AppContext = Depends(get_ctx),
    sess: dict = Depends(require_role("appeal_panel")),
) -> dict:
    return review.decide_appeal(ctx, appeal_id, sess["hotkey"], body.upheld, body.reason)
