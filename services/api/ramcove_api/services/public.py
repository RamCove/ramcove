"""Read projections. Public views never expose private source, unrevealed tests or internal errors."""

from __future__ import annotations

import base64
import json
from datetime import timedelta
from typing import Any

from ramcove_protocol.money import format_tao
from ramcove_protocol.reservation import can_issue_quote
from ramcove_protocol.state import PAID_ACTIVE, TERMINAL, S
from sqlalchemy import func, or_, select

from ..config import ROOT
from ..store.db import now, tx
from ..store.schema import (
    appeals,
    artifacts,
    chain_observations,
    champions,
    comparisons,
    credits,
    incidents,
    jobs,
    quotes,
    receipts,
    refunds,
    reports,
    reviews,
    submissions,
    validators,
    weight_plans,
    workers,
)
from . import banks
from .context import AppContext, ServiceError
from .queue import current_champion


def progress_label(p: dict | None) -> str | None:
    """One line for a stage that is still running. The numbers come from the worker; the wording is here,
    so the dashboard, the submission page and any other reader say the same thing."""
    if not p:
        return None
    step = p.get("step")
    done, total, run = p.get("done"), p.get("total"), p.get("run")
    over = p.get("over_champion_ppm")
    rate = f"{(p.get('rate_milli_rps') or 0) / 1000:.3f} req/s"
    at = "at the champion's score" if not over else f"at the champion's score {over / 1e4:+.1f}%"
    if step == "screen_questions":
        return f"Screening: {done:,} of {total:,} smoke questions answered"
    if step == "quality":
        return f"Question quality: {done:,} of {total:,} answered"
    if step == "champion_answers":
        return f"The champion answers this week's bank: {done:,} of {total:,}"
    if step == "reading":
        return f"Capacity reading {p.get('reading', 1)}: run {run} {at} ({rate})"
    if step == "memory":
        return f"Winner check, memory: tighter-budget reading {p.get('reading', 1)}, run {run} ({rate})"
    if step == "short_request":
        return f"Winner check: short-request control at {rate}"
    if step == "live_conversations":
        return f"Winner check: real conversations at {rate}"
    if step == "soak":
        return f"Winner check: {p.get('minutes', 60)}-minute soak at {rate}"
    if step == "champion_score":
        return f"Measuring the champion's fixed score, from {rate}"
    if step == "champion_tight_score":
        return f"Measuring the champion's score at the tighter cache budget, from {rate}"
    return None


STAGE_LABEL = {
    "preflight_passed": "Checked, not yet reserved",
    "waitlisted": "On the free waiting list",
    "invited": "Invited to reserve capacity",
    "quoted": "Quote issued, awaiting payment",
    "admitted": "Paid, waiting for screening",
    "screening": "Screening (build and smoke checks)",
    "eval_queued": "Waiting for evaluation",
    "evaluating": "Evaluation running",
    "reproduce_queued": "Won, waiting for an independent reproduction",
    "reproducing": "Independent reproduction running",
    "in_review": "Flagged for human review",
    "ready_for_promotion": "Cleared, waiting in admission order",
    "promoted": "Champion",
    "not_promoted": "Did not replace the champion",
    "rejected_preflight": "Rejected by free checks",
    "rejected_screen": "Rejected in screening",
    "review_rejected": "Rejected in review",
    "expired_quote": "Quote expired",
    "expired_unregistered": "Expired: hotkey not registered in time",
    "operator_failed": "Stopped by an operator-side failure",
    "withdrawn": "Withdrawn by the miner",
}


def encode_cursor(values: list[Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(values, default=str).encode()).decode()


def decode_cursor(cursor: str | None) -> list[Any] | None:
    if not cursor:
        return None
    try:
        return json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    except (ValueError, json.JSONDecodeError):
        return None


def mask_hotkey(hk: str | None) -> str | None:
    return None if not hk else f"{hk[:6]}…{hk[-4:]}"


def meta(ctx: AppContext) -> dict:
    return {
        "product": "RamCove",
        "tagline": "More AI. Same GPU.",
        "env": ctx.settings.env,
        "network": ctx.settings.network,
        "simulated_chain": ctx.settings.simulated_chain,
        "chain_writes_enabled": ctx.settings.chain_writes_enabled,
        "demo_features": ctx.settings.demo_features,
        "notice": (
            "The chain, beacon, workers and payments are simulated and labelled; no real tokens move "
            "and no real GPU is measured."
        ),
    }


def overview(ctx: AppContext) -> dict:
    with tx(ctx.engine) as conn:
        profile = ctx.profile(conn)
        champ = current_champion(conn, profile.profile_id)
        ready = ctx.ready_workers(conn, profile.profile_id)
        plan = ctx.capacity_plan(conn, profile, trusted_fixture=True)
        paused = bool(ctx.setting(conn, "intake_paused", {"paused": False}).get("paused"))
        committed = ctx.committed_centi(conn, profile.profile_id)
        check = can_issue_quote(committed, profile.envelope, plan, paused)
        counts = dict(
            conn.execute(select(submissions.c.state, func.count()).group_by(submissions.c.state)).all()
        )
        obs = conn.execute(select(chain_observations)).first()
        history = [
            {
                "version": c.version,
                "author": mask_hotkey(c.author_hotkey),
                "status": c.status,
                "capacity_milli_rps": c.capacity_milli_rps,
                "capacity_measured": c.capacity_measured,
                "bound_gain_ppm": c.bound_gain_ppm,
                "promoted_at": c.promoted_at,
                "simulated": True,
            }
            for c in conn.execute(
                select(champions)
                .where(champions.c.profile_id == profile.profile_id)
                .order_by(champions.c.version)
            ).all()
        ]
        price = ctx.latest_price(conn)
        inc = [
            dict(
                id=i.id,
                severity=i.severity,
                title=i.title,
                summary=i.public_summary,
                started_at=i.started_at,
                resolved_at=i.resolved_at,
            )
            for i in conn.execute(select(incidents).where(incidents.c.resolved_at.is_(None))).all()
        ]
        return {
            "profile": {
                "id": profile.profile_id,
                "version": profile.version,
                "title": profile.title,
                "rule_hash": profile.rule_hash(),
                "measured": profile.measured,
                "bootstrap_mode": profile.bootstrap.mode,
            },
            "champion": {
                "version": champ.version,
                "author": mask_hotkey(champ.author_hotkey),
                "is_baseline": champ.submission_id is None,
                "status": champ.status,
                "capacity_milli_rps": champ.capacity_milli_rps,
                "capacity_measured": champ.capacity_measured,
                "bound_gain_ppm": champ.bound_gain_ppm,
                **champion_measurement(conn, champ),
                "explain": (
                    "No miner holds the crown yet: version 0 is the tuned baseline and earns "
                    "nothing. Until a miner wins, the miner allocation goes to the owner UID (burn)."
                    if champ.submission_id is None
                    else "The champion's author receives this profile's whole miner allocation while "
                    "it stays eligible."
                ),
            },
            "champion_history": history,
            "queue": {
                "counts_by_state": counts,
                "admitted_active": sum(counts.get(s.value, 0) for s in PAID_ACTIVE),
                "waiting_list": counts.get("waitlisted", 0) + counts.get("invited", 0),
            },
            "capacity": {
                "workers_ready": len(ready),
                "workers_total": len(ctx.ready_workers(conn, profile.profile_id, None)),
                "committed_centi_gpu_hours": committed,
                "capacity_centi_gpu_hours": check.capacity_centi,
                "envelope_per_admission_centi": profile.envelope.total(),
                "intake_paused": paused,
                "accepting_paid_submissions": check.allowed,
                "reason": check.reason,
                "horizon_hours": plan.horizon_hours,
            },
            "fee": {
                "flat_fee_rao": profile.fees.flat_fee_rao,
                "flat_fee_tao": format_tao(profile.fees.flat_fee_rao),
                "service_cost_usd_cents": profile.fees.service_cost_usd_cents_per_admission,
                "price_usd_micros": price.usd_micros_per_tao if price else None,
                "price_simulated": price.simulated if price else None,
                "price_observed_at": price.observed_at if price else None,
            },
            "chain": None
            if not obs
            else {
                "network": obs.network,
                "finalized_number": obs.finalized_number,
                "finalized_hash": obs.finalized_hash,
                "genesis_hash": obs.genesis_hash,
                "simulated": obs.simulated,
                "observed_at": obs.observed_at,
            },
            "incidents": inc,
            "meta": meta(ctx),
        }


def profile_detail(ctx: AppContext) -> dict:
    with tx(ctx.engine) as conn:
        profile = ctx.profile(conn)
        champ = current_champion(conn, profile.profile_id)
        latest_plan = conn.execute(
            select(weight_plans).order_by(weight_plans.c.created_at.desc()).limit(1)
        ).first()
        return {
            "profile": profile.model_dump(mode="json", by_alias=True),
            "rule_hash": profile.rule_hash(),
            "champion": {
                "version": champ.version,
                "author": mask_hotkey(champ.author_hotkey),
                "artifact_sha256": champ.artifact_sha256,
                "attribution": champ.attribution,
                "status": champ.status,
                "capacity_milli_rps": champ.capacity_milli_rps,
                "capacity_measured": champ.capacity_measured,
                "promoted_at": champ.promoted_at,
                "bound_gain_ppm": champ.bound_gain_ppm,
            },
            "weight_plan": None if latest_plan is None else latest_plan.body,
            "values_are": "provisional planning values from the v0.2 whitepaper; none is measured on H100",
        }


def queue_page(ctx: AppContext, kind: str = "admitted", cursor: str | None = None, limit: int = 25) -> dict:
    with tx(ctx.engine) as conn:
        states = (
            [s.value for s in PAID_ACTIVE]
            if kind == "admitted"
            else ["waitlisted", "invited"]
            if kind == "waiting"
            else [s.value for s in TERMINAL]
        )
        q = select(submissions).where(submissions.c.state.in_(states))
        c = decode_cursor(cursor)
        if kind == "admitted":
            q = q.order_by(submissions.c.admission_block, submissions.c.admission_index)
            if c:
                q = q.where(
                    or_(
                        submissions.c.admission_block > c[0],
                        (submissions.c.admission_block == c[0]) & (submissions.c.admission_index > c[1]),
                    )
                )
        elif kind == "waiting":
            # the order invitations actually go out in (control.invite_from_waiting_list), oldest first
            q = q.order_by(submissions.c.waitlisted_at, submissions.c.id)
            if c:
                q = q.where(submissions.c.waitlisted_at > c[0])
        else:
            q = q.order_by(submissions.c.updated_at.desc(), submissions.c.id)
            if c:
                q = q.where(submissions.c.updated_at < c[0])
        rows = conn.execute(q.limit(limit + 1)).all()
        more = len(rows) > limit
        rows = rows[:limit]
        items = []
        for r in rows:
            job = conn.execute(
                select(jobs.c.stage, jobs.c.status, jobs.c.lease_worker, jobs.c.progress)
                .where(jobs.c.submission_id == r.id, jobs.c.status.in_(["queued", "leased"]))
                .order_by(jobs.c.created_at.desc())
                .limit(1)
            ).first()
            items.append(
                {
                    "submission_id": r.id,
                    "hotkey": mask_hotkey(r.hotkey),
                    "lineage": r.lineage,
                    "state": r.state,
                    "state_label": STAGE_LABEL.get(r.state, r.state),
                    "admission_key": [r.admission_block, r.admission_index] if r.admission_block else None,
                    "admitted_at": r.admitted_at,
                    "updated_at": r.updated_at,
                    "current_stage": None
                    if not job
                    else {
                        "stage": job.stage,
                        "status": job.status,
                        "worker": job.lease_worker,
                        "progress_label": progress_label(job.progress),
                    },
                    "first_gain_ppm": r.first_gain_ppm,
                    "bound_gain_ppm": r.bound_gain_ppm,
                    "outcome": None
                    if r.state not in {s.value for s in TERMINAL}
                    else {"code": r.outcome_code, "summary": r.outcome_summary, "fee": r.fee_outcome},
                }
            )
        nxt = None
        if more and rows:
            last = rows[-1]
            nxt = encode_cursor(
                [last.admission_block, last.admission_index]
                if kind == "admitted"
                else [last.waitlisted_at]
                if kind == "waiting"
                else [last.updated_at]
            )
        return {
            "kind": kind,
            "items": items,
            "next_cursor": nxt,
            "note": (
                "Paid admissions are ordered by their finalized payment. Workers may run different "
                "submissions at the same time; promotion still follows admission order, so a single "
                "rank across stages would be misleading."
            ),
        }


def submission_view(ctx: AppContext, sub_id: str, viewer: str | None, roles: set[str]) -> dict:
    with tx(ctx.engine) as conn:
        r = conn.execute(select(submissions).where(submissions.c.id == sub_id)).first()
        if r is None:
            return {}
        owner = viewer == r.hotkey
        privileged = owner or bool({"operator", "reviewer"} & roles)
        art = conn.execute(select(artifacts).where(artifacts.c.sha256 == r.artifact_sha256)).first()
        js = conn.execute(
            select(jobs).where(jobs.c.submission_id == sub_id).order_by(jobs.c.created_at)
        ).all()
        cmps = conn.execute(
            select(comparisons)
            .where(comparisons.c.submission_id == sub_id)
            .order_by(comparisons.c.created_at)
        ).all()
        revs = conn.execute(select(reviews).where(reviews.c.submission_id == sub_id)).all()
        aps = conn.execute(select(appeals).where(appeals.c.submission_id == sub_id)).all()
        q = conn.execute(
            select(quotes).where(quotes.c.submission_id == sub_id).order_by(quotes.c.issued_at.desc())
        ).first()
        rc = conn.execute(select(receipts).where(receipts.c.submission_id == sub_id)).first()
        reps = conn.execute(select(reports).where(reports.c.submission_id == sub_id)).all()
        profile = ctx.profile_by_hash(conn, r.rule_hash)
        champ = current_champion(conn, r.profile_id)
        blocking = []
        if r.state == S.READY_FOR_PROMOTION:
            blocking = [
                x.id
                for x in conn.execute(
                    select(submissions.c.id).where(
                        submissions.c.profile_id == r.profile_id,
                        submissions.c.id != r.id,
                        submissions.c.state.in_([s.value for s in PAID_ACTIVE]),
                        or_(
                            submissions.c.admission_block < r.admission_block,
                            (submissions.c.admission_block == r.admission_block)
                            & (submissions.c.admission_index < r.admission_index),
                        ),
                    )
                ).all()
            ]
        out = {
            "submission_id": r.id,
            "state": r.state,
            "state_label": STAGE_LABEL.get(r.state, r.state),
            "hotkey": r.hotkey if privileged else mask_hotkey(r.hotkey),
            "lineage": r.lineage,
            "profile_id": r.profile_id,
            "profile_version": r.profile_version,
            "rule_hash": r.rule_hash,
            "support_ref": r.support_ref,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
            "admission_key": [r.admission_block, r.admission_index] if r.admission_block else None,
            "admitted_at": r.admitted_at,
            "compared_champion_version": r.compared_champion_version,
            "current_champion_version": champ.version,
            "first_gain_ppm": r.first_gain_ppm,
            "bound_gain_ppm": r.bound_gain_ppm,
            "margin_ppm": profile.replacement.delta_ppm,
            "clear_win_ppm": profile.replacement.clear_win_ppm,
            "outcome": {"code": r.outcome_code, "summary": r.outcome_summary, "fee": r.fee_outcome},
            "method": art.manifest.get("method") if art else None,
            "mechanism": art.manifest.get("mechanism") if art else None,
            "trusted_fixture": art.trusted_fixture if art else None,
            "changed_paths": art.changed_paths if (privileged and art) else None,
            "artifact_sha256": r.artifact_sha256 if privileged else None,
            "blocking_submissions": blocking,
            # a winner must have its hotkey registered before this, or the submission expires unpromoted
            "registration_deadline": (
                r.ready_since + timedelta(seconds=profile.deadlines.registration_grace_s)
                if r.ready_since and r.state == S.READY_FOR_PROMOTION.value
                else None
            ),
            "timeline": [
                {
                    "stage": j.stage,
                    "status": j.status,
                    "worker": j.lease_worker,
                    "champion_version": j.champion_version,
                    "attempts": j.attempts,
                    "progress_label": progress_label(j.progress) if j.status == "leased" else None,
                    "created_at": j.created_at,
                    "updated_at": j.updated_at,
                    "lease_expires_at": j.lease_expires_at,
                    "gpu_centi_used": j.gpu_centi_used,
                }
                for j in js
            ],
            "comparisons": [
                {
                    "id": c.id,
                    "champion_version": c.champion_version,
                    "status": c.status,
                    "validator": mask_hotkey(c.validator),
                    "worker": c.worker,
                    "anchor_block": c.anchor_block,
                    "beacon_round": c.beacon_round,
                    "beacon_simulated": c.beacon_simulated,
                    "void_reason": c.void_reason,
                    "challenger_milli_rps": c.challenger_milli_rps,
                    "champion_milli_rps": c.champion_milli_rps,
                }
                for c in cmps
            ],
            "reviews": [
                {
                    "id": v.id,
                    "reviewer": mask_hotkey(v.reviewer),
                    "decision": v.decision,
                    "criteria": v.criteria,
                    "reasons": v.reasons,
                    "due_at": v.due_at,
                    "decided_at": v.decided_at,
                }
                for v in revs
            ],
            "appeals": [
                {
                    "id": a.id,
                    "status": a.status,
                    "kind": a.kind,
                    "grounds": a.grounds,
                    "decided_by": mask_hotkey(a.decided_by),
                    "decision_reason": a.decision_reason,
                    "due_at": a.due_at,
                }
                for a in aps
            ],
            "reports": [
                {
                    "id": p.id,
                    "kind": p.kind,
                    "hash": p.hash,
                    "simulated": p.simulated,
                    "body": p.public_body if (privileged or p.kind != "screen") else None,
                    "created_at": p.created_at,
                }
                for p in reps
            ],
            "simulated": True,
        }
        if privileged and q:
            out["quote"] = {
                "id": q.id,
                "amount_rao": q.amount_rao,
                "amount_tao": format_tao(q.amount_rao),
                "status": q.status,
                "expires_block": q.expires_block,
                "payer": q.payer,
                "recipient": q.recipient,
                "body": q.body,
                "signature": q.signature,
                "price_simulated": q.price_simulated,
                "service_cost_usd_cents": q.service_cost_usd_cents,
                "fee_usd_cents": q.fee_usd_cents,
            }
        if privileged and rc:
            out["receipt"] = {"id": rc.id, "body": rc.body, "signature": rc.signature, "signer": rc.signer}
        if privileged:
            out["credits"] = [
                {
                    "id": c.id,
                    "amount_rao": c.amount_rao,
                    "reason": c.reason,
                    "expires_at": c.expires_at,
                    "consumed_by": c.consumed_by,
                }
                for c in conn.execute(select(credits).where(credits.c.source_submission == sub_id)).all()
            ]
            out["refunds"] = [
                {"id": f.id, "amount_rao": f.amount_rao, "status": f.status, "reason": f.reason}
                for f in conn.execute(select(refunds).where(refunds.c.submission_id == sub_id)).all()
            ]
        return out


def my_submissions(ctx: AppContext, hotkey: str) -> dict:
    with tx(ctx.engine) as conn:
        rows = conn.execute(
            select(submissions)
            .where(submissions.c.hotkey == hotkey)
            .order_by(submissions.c.created_at.desc())
            .limit(100)
        ).all()
        cr = conn.execute(
            select(credits).where(credits.c.hotkey == hotkey, credits.c.consumed_by.is_(None))
        ).all()
        return {
            "items": [
                {
                    "submission_id": r.id,
                    "state": r.state,
                    "state_label": STAGE_LABEL.get(r.state, r.state),
                    "lineage": r.lineage,
                    "created_at": r.created_at,
                    "updated_at": r.updated_at,
                    "admission_key": [r.admission_block, r.admission_index] if r.admission_block else None,
                    "outcome": {"code": r.outcome_code, "summary": r.outcome_summary, "fee": r.fee_outcome},
                    "support_ref": r.support_ref,
                    "first_gain_ppm": r.first_gain_ppm,
                    "bound_gain_ppm": r.bound_gain_ppm,
                }
                for r in rows
            ],
            "credits": [
                {
                    "id": c.id,
                    "amount_rao": c.amount_rao,
                    "amount_tao": format_tao(c.amount_rao),
                    "reason": c.reason,
                    "expires_at": c.expires_at,
                }
                for c in cr
            ],
        }


def validator_workspace(ctx: AppContext, hotkey: str) -> dict:
    with tx(ctx.engine) as conn:
        v = conn.execute(select(validators).where(validators.c.hotkey == hotkey)).first()
        if v is None:
            return {"validator": None}
        ws = conn.execute(select(workers).where(workers.c.validator == hotkey)).all()
        obs = conn.execute(select(chain_observations)).first()
        profile = ctx.profile(conn)
        champ = current_champion(conn, profile.profile_id)
        pend = conn.execute(
            select(jobs)
            .where(jobs.c.status.in_(["queued", "leased"]))
            .order_by(jobs.c.priority_block, jobs.c.priority_index)
            .limit(50)
        ).all()
        cmps = conn.execute(
            select(comparisons)
            .where(comparisons.c.validator == hotkey)
            .order_by(comparisons.c.created_at.desc())
            .limit(20)
        ).all()
        return {
            "validator": {
                "hotkey": hotkey,
                "name": v.name,
                "scoring": v.scoring,
                "operator_affiliated": v.operator_affiliated,
                "independence_group": v.independence_group,
                "stake_share_bp": v.stake_share_bp,
            },
            "workers": [
                {
                    "id": w.id,
                    "provider": w.provider,
                    "online": bool(w.last_heartbeat and now() - w.last_heartbeat < timedelta(seconds=120)),
                    "safe_and_ready": w.ready,
                    "readiness": w.readiness,
                    "calibrated_champion_version": w.calibrated_champion_version,
                    "calibrated_at": w.calibrated_at,
                    "enabled": w.enabled,
                    "calibration_current": w.calibrated_champion_version == champ.version,
                }
                for w in ws
            ],
            "queue": [
                {
                    "job_id": j.id,
                    "stage": j.stage,
                    "status": j.status,
                    "submission_id": j.submission_id,
                    "priority": [j.priority_block, j.priority_index],
                    "lease_worker": j.lease_worker,
                    "lease_expires_at": j.lease_expires_at,
                }
                for j in pend
            ],
            "comparisons": [
                {
                    "id": c.id,
                    "submission_id": c.submission_id,
                    "status": c.status,
                    "champion_version": c.champion_version,
                    "beacon_round": c.beacon_round,
                    "worker": c.worker,
                    "challenger_milli_rps": c.challenger_milli_rps,
                    "champion_milli_rps": c.champion_milli_rps,
                }
                for c in cmps
            ],
            "chain": None
            if not obs
            else {
                "finalized_number": obs.finalized_number,
                "simulated": obs.simulated,
                "observed_at": obs.observed_at,
                "genesis_hash": obs.genesis_hash,
            },
            "reimbursement_note": (
                "Reproduction work is reimbursed per run at the published rate; this build "
                "records the policy but moves no funds."
            ),
        }


def question_banks(ctx: AppContext) -> dict:
    with tx(ctx.engine) as conn:
        return banks.public_banks(conn, ctx.profile(conn))


def status_page(ctx: AppContext) -> dict:
    with tx(ctx.engine) as conn:
        profile = ctx.profile(conn)
        ws = conn.execute(select(workers)).all()
        obs = conn.execute(select(chain_observations)).first()
        inc = conn.execute(select(incidents).order_by(incidents.c.started_at.desc()).limit(20)).all()
        stuck = conn.execute(
            select(func.count())
            .select_from(jobs)
            .where(jobs.c.status == "leased", jobs.c.lease_expires_at < now())
        ).scalar()
        return {
            "profile": profile.profile_id,
            "workers": [
                {
                    "id": w.id,
                    "online": bool(w.last_heartbeat and now() - w.last_heartbeat < timedelta(seconds=120)),
                    "safe_and_ready": w.ready,
                    "provider": w.provider,
                    "untrusted_code_isolation": bool(w.readiness.get("untrusted_code_isolation")),
                }
                for w in ws
            ],
            "fixed_scores": worker_fixed_scores(ws, current_champion(conn, profile.profile_id).version),
            "expired_leases_waiting_for_sweep": stuck,
            "chain": None
            if not obs
            else {
                "finalized_number": obs.finalized_number,
                "simulated": obs.simulated,
                "observed_at": obs.observed_at,
            },
            "incidents": [
                {
                    "id": i.id,
                    "severity": i.severity,
                    "title": i.title,
                    "summary": i.public_summary,
                    "started_at": i.started_at,
                    "resolved_at": i.resolved_at,
                }
                for i in inc
            ],
            "meta": meta(ctx),
        }


def audit_page(ctx: AppContext, public_only: bool, cursor: str | None, limit: int = 50) -> dict:
    from ..store.schema import audit_events

    with tx(ctx.engine) as conn:
        q = select(audit_events).order_by(audit_events.c.id.desc()).limit(limit + 1)
        if public_only:
            q = q.where(audit_events.c.public)
        c = decode_cursor(cursor)
        if c:
            q = q.where(audit_events.c.id < c[0])
        rows = conn.execute(q).all()
        more = len(rows) > limit
        rows = rows[:limit]
        return {
            "items": [
                {
                    "id": r.id,
                    "at": r.at,
                    "actor": r.actor if not public_only else mask_hotkey(r.actor),
                    "action": r.action,
                    "subject_type": r.subject_type,
                    "subject_id": r.subject_id,
                    "data": r.data,
                    "hash": r.hash,
                }
                for r in rows
            ],
            "next_cursor": encode_cursor([rows[-1].id]) if more and rows else None,
        }


def verify_audit(ctx: AppContext) -> dict:
    from ..store import audit as audit_mod

    with tx(ctx.engine) as conn:
        ok, n, bad = audit_mod.verify_chain(conn)
        return {"ok": ok, "events_checked": n, "first_bad_event_id": bad}


# Status groups shown on the miners' dashboard. Every state belongs to exactly one group.
DASHBOARD_GROUPS: dict[str, frozenset[str]] = {
    "in_progress": frozenset(s.value for s in PAID_ACTIVE),
    "waiting": frozenset({S.PREFLIGHT_PASSED.value, S.WAITLISTED.value, S.INVITED.value, S.QUOTED.value}),
    "promoted": frozenset({S.PROMOTED.value}),
    "rejected": frozenset(
        {
            S.NOT_PROMOTED.value,
            S.REJECTED_PREFLIGHT.value,
            S.REJECTED_SCREEN.value,
            S.REVIEW_REJECTED.value,
            S.EXPIRED_UNREGISTERED.value,
        }
    ),
    "closed": frozenset({S.WITHDRAWN.value, S.EXPIRED_QUOTE.value, S.OPERATOR_FAILED.value}),
}


def workflow(profile) -> list[dict]:
    """The whole path a submission takes, with the numbers taken from the rules that will run it, so the
    site cannot drift from the evaluator. GPU time is in centi-GPU-hours."""
    from ramcove_evaluator.pipeline import CHECK_CENTI, QUALITY_CENTI, RUN_CENTI

    q = profile.question_bank
    screening = q.screening_long + q.screening_general
    offline = q.offline_long + q.offline_general
    rep = profile.replacement
    env = profile.envelope
    step_pct = rep.grid_step_ppm / 1e4
    return [
        {
            "key": "preflight",
            "name": "Free checks",
            "what": "Signature, manifest, patch scope and duplicate check. No GPU, no fee, no queue place.",
            "when": "Every submission",
            "gpu_centi": 0,
            "states": ["preflight_passed", "rejected_preflight"],
        },
        {
            "key": "admission",
            "name": "Quote, payment, queue place",
            "what": (
                f"A flat fee of {format_tao(profile.fees.flat_fee_rao).rstrip('0').rstrip('.')} TAO books "
                f"{env.total() / 100:.2f} GPU-hours: screening plus one evaluation. The payment block and "
                "index fix the order."
            ),
            "when": "After a quote is accepted",
            "gpu_centi": 0,
            "states": ["quoted", "admitted"],
        },
        {
            "key": "screen",
            "name": "Screening",
            "what": (
                f"Build, engine start, {screening:,} questions from this week's owner bank and the memory "
                "ceiling. A failure here ends the submission and the fee is consumed."
            ),
            "when": "Once, before any measurement",
            "gpu_centi": env.screen,
            "states": ["screening", "rejected_screen"],
        },
        {
            "key": "quality",
            "name": "Question quality",
            "what": (
                f"The challenger answers all {offline:,} bank questions. Its answers are set against the "
                "champion's answers to the same questions and against a frozen reference. Failing ends the "
                "evaluation before any capacity is measured."
            ),
            "when": "First half of the evaluation",
            "gpu_centi": QUALITY_CENTI + CHECK_CENTI,
            "states": ["eval_queued", "evaluating"],
        },
        {
            "key": "reading",
            "name": "Capacity reading",
            "what": (
                f"Eight-minute runs, starting at the champion's fixed score and stepping up {step_pct:.0f}% "
                "after every run that passes the gates. The reading is the last rate that passed; it stops "
                "at the first run that fails."
            ),
            "when": "Second half of the evaluation",
            "gpu_centi": RUN_CENTI,
            "states": ["evaluating"],
        },
        {
            "key": "rule",
            "name": "The rule",
            "what": (
                f"A reading at or below {rep.delta_ppm / 1e4:.0f}% loses. One at or above "
                f"{rep.clear_win_ppm / 1e4:.0f}% wins. In between, one more reading is taken and the average "
                "of the two must clear the margin."
            ),
            "when": "As soon as the reading is in",
            "gpu_centi": 0,
            "states": ["evaluating", "not_promoted"],
        },
        {
            "key": "winner_checks",
            "name": "Winner checks",
            "what": (
                "Only for a winner, and paid from the reserve rather than the miner's booking: attainment "
                "across context bands, memory evidence at a 25% smaller cache budget, a short-request "
                "control, real multi-turn conversations, and an hour-long soak at 90% of the measured "
                "capacity."
            ),
            "when": "Only after a winning reading",
            "gpu_centi": env.winner_checks,
            "states": ["evaluating"],
        },
        {
            "key": "promotion",
            "name": "Promotion",
            "what": (
                "Automatic unless an automatic check flagged the work for a person. The new champion's code "
                "is published, the weight plan is written, and the champion's fixed score is measured again "
                "on every worker."
            ),
            "when": "In admission order",
            "gpu_centi": env.recalibration_on_promotion,
            "states": ["in_review", "ready_for_promotion", "promoted"],
        },
    ]


def champion_measurement(conn, champ) -> dict:
    """Capacity is measured per worker, so two numbers on this site have different baselines: the champion's
    capacity is one worker's measurement, and its gain was taken against the fixed score of the worker that
    judged it. Say both, or a reader cannot reconcile them."""
    out: dict = {"measured_against_milli_rps": None, "measured_on_worker": None, "reading_milli_rps": None}
    if not champ or not champ.submission_id:
        return out
    row = conn.execute(
        select(comparisons)
        .where(comparisons.c.submission_id == champ.submission_id, comparisons.c.status == "measured")
        .order_by(comparisons.c.created_at.desc())
    ).first()
    if row:
        out.update(
            measured_against_milli_rps=row.champion_milli_rps,
            measured_on_worker=row.worker,
            reading_milli_rps=row.challenger_milli_rps,
        )
    return out


def worker_fixed_scores(ws, champion_version: int | None) -> list[dict]:
    """Each worker's own fixed score for the champion it has calibrated. The spread between workers is real
    and is why a gain is never taken against another worker's number."""
    out = []
    for w in ws:
        cal = (w.readiness or {}).get("calibration") or {}
        if cal.get("capacity_milli_rps"):
            out.append(
                {
                    "worker": w.id,
                    "champion_version": w.calibrated_champion_version,
                    "current": w.calibrated_champion_version == champion_version,
                    "fixed_score_milli_rps": cal.get("capacity_milli_rps"),
                    "tight_fixed_score_milli_rps": cal.get("tight_capacity_milli_rps"),
                    "measured_at": w.calibrated_at,
                }
            )
    return sorted(out, key=lambda r: r["worker"])


def dashboard_group(state: str) -> str:
    for group, states in DASHBOARD_GROUPS.items():
        if state in states:
            return group
    return "in_progress"


def dashboard(ctx: AppContext, limit: int = 80) -> dict:
    """Everything a miner needs at a glance: the champion, where every submission stands, why the
    rejected ones ended, and how each miner is doing. Public fields only; hotkeys are masked."""
    with tx(ctx.engine) as conn:
        profile = ctx.profile(conn)
        champ = current_champion(conn, profile.profile_id)
        counts = {g: 0 for g in DASHBOARD_GROUPS}
        for state, n in conn.execute(
            select(submissions.c.state, func.count())
            .where(submissions.c.profile_id == profile.profile_id)
            .group_by(submissions.c.state)
        ):
            counts[dashboard_group(state)] += n
        rows = conn.execute(
            select(submissions)
            .where(submissions.c.profile_id == profile.profile_id)
            .order_by(submissions.c.updated_at.desc(), submissions.c.id)
            .limit(limit)
        ).all()
        shas = {r.artifact_sha256 for r in rows if r.artifact_sha256}
        arts = (
            {a.sha256: a for a in conn.execute(select(artifacts).where(artifacts.c.sha256.in_(shas)))}
            if shas
            else {}
        )
        ids = [r.id for r in rows]
        live_jobs = {}
        if ids:
            for j in conn.execute(
                select(jobs)
                .where(jobs.c.submission_id.in_(ids), jobs.c.status.in_(["queued", "leased"]))
                .order_by(jobs.c.created_at)
            ):
                live_jobs.setdefault(j.submission_id, j)
        items = []
        for r in rows:
            art = arts.get(r.artifact_sha256)
            job = live_jobs.get(r.id)
            items.append(
                {
                    "submission_id": r.id,
                    "hotkey": mask_hotkey(r.hotkey),
                    "lineage": r.lineage,
                    "method": art.manifest.get("title") or art.manifest.get("method") if art else None,
                    "mechanism": art.manifest.get("mechanism") if art else None,
                    "trusted_fixture": art.trusted_fixture if art else None,
                    "state": r.state,
                    "state_label": STAGE_LABEL.get(r.state, r.state),
                    "group": dashboard_group(r.state),
                    "current_stage": None
                    if job is None
                    else {
                        "stage": job.stage,
                        "status": job.status,
                        "progress": job.progress,
                        "progress_label": progress_label(job.progress),
                        "progress_at": job.progress_at,
                    },
                    "first_gain_ppm": r.first_gain_ppm,
                    "bound_gain_ppm": r.bound_gain_ppm,
                    "outcome": None
                    if not r.outcome_code
                    else {"code": r.outcome_code, "summary": r.outcome_summary, "fee": r.fee_outcome},
                    "created_at": r.created_at,
                    "updated_at": r.updated_at,
                }
            )
        reasons: dict[str, dict] = {}
        for r in rows:
            if dashboard_group(r.state) == "rejected" and r.outcome_code:
                entry = reasons.setdefault(
                    r.outcome_code, {"code": r.outcome_code, "count": 0, "example": None}
                )
                entry["count"] += 1
                entry["example"] = entry["example"] or r.outcome_summary
        miners: dict[str, dict] = {}
        for r in conn.execute(
            select(submissions.c.hotkey, submissions.c.state, submissions.c.bound_gain_ppm).where(
                submissions.c.profile_id == profile.profile_id
            )
        ):
            m = miners.setdefault(
                r.hotkey,
                {
                    "hotkey": mask_hotkey(r.hotkey),
                    "submissions": 0,
                    "promoted": 0,
                    "rejected": 0,
                    "best_bound_gain_ppm": None,
                },
            )
            m["submissions"] += 1
            group = dashboard_group(r.state)
            if group in ("promoted", "rejected"):
                m[group] += 1
            if r.bound_gain_ppm is not None:
                best = m["best_bound_gain_ppm"]
                m["best_bound_gain_ppm"] = r.bound_gain_ppm if best is None else max(best, r.bound_gain_ppm)
        champ_hotkey = champ.author_hotkey if champ else None
        leaderboard = sorted(
            miners.items(),
            key=lambda kv: (
                kv[0] != champ_hotkey,
                -kv[1]["promoted"],
                -(kv[1]["best_bound_gain_ppm"] or -(10**9)),
            ),
        )
        return {
            "profile": {"id": profile.profile_id, "version": profile.version, "title": profile.title},
            "champion": {
                "version": champ.version,
                "author": mask_hotkey(champ.author_hotkey),
                "is_baseline": champ.author_hotkey is None,
                "capacity_milli_rps": champ.capacity_milli_rps,
                "bound_gain_ppm": champ.bound_gain_ppm,
                "promoted_at": champ.promoted_at,
                **champion_measurement(conn, champ),
            },
            "fixed_scores": worker_fixed_scores(
                conn.execute(select(workers)).all(), champ.version if champ else None
            ),
            "counts": counts,
            "total": sum(counts.values()),
            "workflow": workflow(profile),
            "running": [
                i for i in items if i["current_stage"] and i["current_stage"].get("status") == "leased"
            ],
            "items": items,
            "rejection_reasons": sorted(reasons.values(), key=lambda e: -e["count"]),
            "miners": [{**m, "is_champion": hk == champ_hotkey} for hk, m in leaderboard][:20],
            "simulated": True,
            "generated_at": now(),
        }


def champion_stack(conn, profile_id: str, version: int) -> list[dict]:
    """The champion patches that make up a champion's stack, oldest first: each champion's code is a patch on
    the champion it declared as its parent, down to the baseline (version 0, which has no patch)."""
    chain: list[dict] = []
    seen: set[int] = set()
    while version and version not in seen:
        seen.add(version)
        row = conn.execute(
            select(champions).where(champions.c.profile_id == profile_id, champions.c.version == version)
        ).first()
        if row is None or not row.artifact_sha256:
            break
        art = conn.execute(select(artifacts).where(artifacts.c.sha256 == row.artifact_sha256)).first()
        chain.append(
            {
                "version": row.version,
                "author": mask_hotkey(row.author_hotkey),
                "artifact_sha256": row.artifact_sha256,
                "method": (art.manifest or {}).get("method") if art else None,
                "download": f"/v1/champions/{row.version}/artifact",
            }
        )
        version = int((art.manifest or {}).get("parent_champion_version", 0)) if art else 0
    return list(reversed(chain))


def champion_code(ctx: AppContext) -> dict:
    """What a miner downloads to build on the champion: the champion's patches in order (a few kilobytes), the
    engine commit they apply to, and the engine settings. RamCove does not host the engine itself."""
    with tx(ctx.engine) as conn:
        profile = ctx.profile(conn)
        champ = current_champion(conn, profile.profile_id)
        path = ROOT / "config" / "engine_args" / f"{profile.profile_id}@{profile.version}.json"
        return {
            "engine": profile.engine.model_dump(),
            "model": {"repo": profile.model.repo, "revision": profile.model.revision},
            "engine_args": json.loads(path.read_text()) if path.exists() else None,
            "current_champion_version": champ.version,
            "patches": champion_stack(conn, profile.profile_id, champ.version),
        }


def champion_artifact(ctx: AppContext, version: int) -> bytes:
    """A promoted champion's code is public: its signed artifact, a tar.gz with manifest.json and patch.diff."""
    with tx(ctx.engine) as conn:
        profile = ctx.profile(conn)
        row = conn.execute(
            select(champions).where(
                champions.c.profile_id == profile.profile_id, champions.c.version == version
            )
        ).first()
        if row is None:
            raise ServiceError("not_found", f"there is no champion version {version}", 404)
        if not row.artifact_sha256:
            raise ServiceError(
                "baseline", "version 0 is the unmodified engine at the pinned commit; it has no patch", 404
            )
        art = conn.execute(select(artifacts).where(artifacts.c.sha256 == row.artifact_sha256)).first()
    return ctx.artifacts.get(art.storage_key)
