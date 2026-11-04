"""Operator console. No route crowns a champion by hand or rewrites a measured score."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from ..services import public
from ..services.context import AppContext
from ..services.settlement import suspend_and_rollback
from ..store import audit
from ..store.db import new_id, now, tx
from ..store.schema import (
    incidents,
    jobs,
    profile_versions,
    reviews,
    submissions,
    workers,
)
from ..store.schema import (
    settings as settings_t,
)
from .deps import get_ctx, require_role

router = APIRouter(prefix="/v1/operator", tags=["operator"])


class PauseIn(BaseModel):
    paused: bool
    reason: str = Field(min_length=5, max_length=500)


class ExcludeIn(BaseModel):
    hotkey: str = Field(min_length=40, max_length=48)
    excluded: bool
    reason: str = Field(min_length=5, max_length=500)


class IncidentIn(BaseModel):
    severity: str = Field(pattern="^(info|minor|major|critical)$")
    title: str = Field(min_length=5, max_length=200)
    public_summary: str = Field(min_length=10, max_length=2000)


class RollbackIn(BaseModel):
    reason: str = Field(min_length=10, max_length=1000)
    deliberate: bool = False


@router.get("/console")
def console(ctx: AppContext = Depends(get_ctx), sess: dict = Depends(require_role("operator"))) -> dict:
    with tx(ctx.engine) as conn:
        profile = ctx.profile(conn)
        by_state = dict(
            conn.execute(select(submissions.c.state, func.count()).group_by(submissions.c.state)).all()
        )
        leases = conn.execute(
            select(jobs).where(jobs.c.status == "leased").order_by(jobs.c.lease_expires_at)
        ).all()
        queued = conn.execute(
            select(jobs.c.stage, func.count()).where(jobs.c.status == "queued").group_by(jobs.c.stage)
        ).all()
        revs = conn.execute(select(reviews).where(reviews.c.decision.is_(None))).all()
        incs = conn.execute(select(incidents).order_by(incidents.c.started_at.desc()).limit(20)).all()
        vers = conn.execute(select(profile_versions)).all()
        ws = conn.execute(select(workers)).all()
        return {
            "intake": {
                "paused": bool(ctx.setting(conn, "intake_paused", {"paused": False}).get("paused")),
                "committed_centi": ctx.committed_centi(conn, profile.profile_id),
                "envelope_per_admission_centi": profile.envelope.total(),
            },
            "submissions_by_state": by_state,
            "queued_jobs": {stage: n for stage, n in queued},
            "leases": [
                {
                    "job_id": j.id,
                    "stage": j.stage,
                    "worker": j.lease_worker,
                    "submission_id": j.submission_id,
                    "expires_at": j.lease_expires_at,
                    "attempts": j.attempts,
                    "expired": bool(j.lease_expires_at and j.lease_expires_at < now()),
                }
                for j in leases
            ],
            "open_reviews": [
                {
                    "id": r.id,
                    "submission_id": r.submission_id,
                    "due_at": r.due_at,
                    "overdue": r.due_at < now(),
                }
                for r in revs
            ],
            "incidents": [
                {
                    "id": i.id,
                    "severity": i.severity,
                    "title": i.title,
                    "summary": i.public_summary,
                    "started_at": i.started_at,
                    "resolved_at": i.resolved_at,
                }
                for i in incs
            ],
            "profile_versions": [
                {
                    "profile_id": v.profile_id,
                    "version": v.version,
                    "rule_hash": v.rule_hash,
                    "active": v.active,
                    "published_at": v.published_at,
                }
                for v in vers
            ],
            "workers": [
                {
                    "id": w.id,
                    "validator": w.validator,
                    "ready": w.ready,
                    "readiness": w.readiness,
                    "enabled": w.enabled,
                    "calibrated_champion_version": w.calibrated_champion_version,
                }
                for w in ws
            ],
            "guardrails": [
                "No route sets a champion by hand.",
                "No route edits a measured score.",
                "Emergency rollback keeps the suspended version and its evidence.",
            ],
        }


@router.post("/intake")
def set_intake(
    body: PauseIn, ctx: AppContext = Depends(get_ctx), sess: dict = Depends(require_role("operator"))
) -> dict:
    with tx(ctx.engine) as conn:
        conn.execute(
            insert(settings_t)
            .values(
                key="intake_paused",
                value={"paused": body.paused},
                updated_by=sess["hotkey"],
                reason=body.reason,
            )
            .on_conflict_do_update(
                index_elements=["key"],
                set_={
                    "value": {"paused": body.paused},
                    "updated_by": sess["hotkey"],
                    "reason": body.reason,
                    "updated_at": now(),
                },
            )
        )
        audit.append(
            conn,
            sess["hotkey"],
            "intake_paused" if body.paused else "intake_resumed",
            "settings",
            "intake_paused",
            {"reason": body.reason},
            public=True,
        )
    return {"paused": body.paused, "reason": body.reason}


@router.post("/exclusions")
def set_exclusion(
    body: ExcludeIn, ctx: AppContext = Depends(get_ctx), sess: dict = Depends(require_role("operator"))
) -> dict:
    """Exclude a hotkey, or reinstate it. An excluded hotkey is refused in the free checks, before it can
    take a queue place, and the decision is published in the audit log with its reason."""
    with tx(ctx.engine) as conn:
        current = dict((ctx.setting(conn, "excluded_hotkeys", {}) or {}).get("hotkeys") or {})
        if body.excluded:
            current[body.hotkey] = body.reason
        else:
            current.pop(body.hotkey, None)
        value = {"hotkeys": current}
        conn.execute(
            insert(settings_t)
            .values(key="excluded_hotkeys", value=value, updated_by=sess["hotkey"], reason=body.reason)
            .on_conflict_do_update(
                index_elements=["key"],
                set_={
                    "value": value,
                    "updated_by": sess["hotkey"],
                    "reason": body.reason,
                    "updated_at": now(),
                },
            )
        )
        audit.append(
            conn,
            sess["hotkey"],
            "hotkey_excluded" if body.excluded else "hotkey_reinstated",
            "hotkey",
            body.hotkey,
            {"reason": body.reason},
            public=True,
        )
    return {"hotkey": body.hotkey, "excluded": body.excluded, "reason": body.reason}


@router.post("/incidents")
def open_incident(
    body: IncidentIn, ctx: AppContext = Depends(get_ctx), sess: dict = Depends(require_role("operator"))
) -> dict:
    iid = new_id("inc")
    with tx(ctx.engine) as conn:
        conn.execute(
            incidents.insert().values(
                id=iid,
                severity=body.severity,
                title=body.title,
                public_summary=body.public_summary,
                opened_by=sess["hotkey"],
            )
        )
        audit.append(
            conn, sess["hotkey"], "incident_opened", "incident", iid, {"severity": body.severity}, public=True
        )
    return {"id": iid}


@router.post("/incidents/{incident_id}/resolve")
def resolve_incident(
    incident_id: str, ctx: AppContext = Depends(get_ctx), sess: dict = Depends(require_role("operator"))
) -> dict:
    from sqlalchemy import update

    with tx(ctx.engine) as conn:
        conn.execute(update(incidents).where(incidents.c.id == incident_id).values(resolved_at=now()))
        audit.append(conn, sess["hotkey"], "incident_resolved", "incident", incident_id, {}, public=True)
    return {"id": incident_id, "resolved": True}


@router.post("/champion/rollback")
def rollback(
    body: RollbackIn, ctx: AppContext = Depends(get_ctx), sess: dict = Depends(require_role("operator"))
) -> dict:
    with tx(ctx.engine) as conn:
        profile = ctx.profile(conn)
        return suspend_and_rollback(
            conn, ctx, profile.profile_id, sess["hotkey"], body.reason, body.deliberate
        )


@router.get("/audit")
def audit_log(
    cursor: str | None = None,
    ctx: AppContext = Depends(get_ctx),
    sess: dict = Depends(require_role("operator")),
) -> dict:
    return public.audit_page(ctx, public_only=False, cursor=cursor)


@router.get("/audit/verify")
def verify(ctx: AppContext = Depends(get_ctx), sess: dict = Depends(require_role("operator"))) -> dict:
    return public.verify_audit(ctx)
