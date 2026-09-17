"""Leases, job results and stage transitions (Sections 6.4, 7.8; review R2-R4).

Dispatch order = oldest admission key first among compatible queued jobs. Completion order is free.
Promotion order is enforced separately in settlement.py.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from room_chain.beacon import DevBeacon, resolve_round
from room_protocol.reservation import remaining_envelope
from room_protocol.scoring import Block, replacement_bound
from room_protocol.state import S
from sqlalchemy import Connection, and_, func, select, update

from ..store import audit
from ..store.db import new_id, now, tx
from ..store.schema import (
    artifacts,
    champion_pointer,
    champions,
    comparisons,
    jobs,
    reports,
    reviews,
    submissions,
    validators,
    workers,
)
from .accounting import issue_credit, ledger_entry
from .context import AppContext, ServiceError
from .intake import _set_state, lock_submission

CALIBRATION_VALID_DAYS = 7
STAGE_LEASE = {
    "screen": "lease_screen_s",
    "full": "lease_full_s",
    "confirm_block": "lease_block_s",
    "calibration": "lease_full_s",
}


def current_champion(conn: Connection, profile_id: str):
    v = conn.execute(
        select(champion_pointer.c.version).where(champion_pointer.c.profile_id == profile_id)
    ).scalar()
    if v is None:
        raise ServiceError("no_champion_record", "profile has no champion record", 500)
    return conn.execute(
        select(champions).where(champions.c.profile_id == profile_id, champions.c.version == v)
    ).first()


def _set_reserved(conn: Connection, ctx: AppContext, sub_id: str) -> None:
    sub = conn.execute(select(submissions).where(submissions.c.id == sub_id)).first()
    profile = ctx.profile_by_hash(conn, sub.rule_hash)
    conn.execute(
        update(submissions)
        .where(submissions.c.id == sub_id)
        .values(
            reserved_centi=remaining_envelope(
                S(sub.state), profile.envelope, sub.rebases_used, profile.deadlines.max_rebases
            )
        )
    )


def transition(conn: Connection, ctx: AppContext, sub_id: str, event: str, **values: Any) -> str:
    sub = lock_submission(conn, sub_id)
    new = _set_state(conn, sub_id, sub.state, event, **values)
    _set_reserved(conn, ctx, sub_id)
    return new


def champion_payload(conn: Connection, champ) -> dict:
    if champ.submission_id is None:
        return {"version": champ.version, "kind": "baseline", "artifact_sha256": None}
    return {"version": champ.version, "kind": "artifact", "artifact_sha256": champ.artifact_sha256}


def lease_next(ctx: AppContext, worker_id: str) -> dict | None:
    with tx(ctx.engine) as conn:
        w = conn.execute(select(workers).where(workers.c.id == worker_id).with_for_update()).first()
        if w is None or not w.enabled:
            raise ServiceError("unknown_worker", "worker is not registered or disabled", 403)
        if not w.ready:
            return None
        profile = ctx.profile(conn, w.profile_id)
        champ = current_champion(conn, w.profile_id)
        stale_cal = (
            w.calibrated_champion_version != champ.version
            or w.calibrated_at is None
            or now() - w.calibrated_at > timedelta(days=CALIBRATION_VALID_DAYS)
        )
        if stale_cal:
            job = conn.execute(
                select(jobs)
                .where(
                    jobs.c.stage == "calibration",
                    jobs.c.lease_worker == worker_id,
                    jobs.c.champion_version == champ.version,
                    jobs.c.status.in_(["queued", "leased"]),
                )
                .with_for_update()
            ).first()
            if job is None:
                jid = new_id("job")
                conn.execute(
                    jobs.insert().values(
                        id=jid,
                        profile_id=w.profile_id,
                        stage="calibration",
                        priority_block=0,
                        priority_index=0,
                        champion_version=champ.version,
                        rule_hash=profile.rule_hash(),
                        lease_worker=worker_id,
                    )
                )
                job = conn.execute(select(jobs).where(jobs.c.id == jid)).first()
            if job.status == "leased" and job.lease_expires_at and job.lease_expires_at > now():
                return None
            return _lease(conn, ctx, job, worker_id, profile, champ)
        others_ready = len(ctx.ready_workers(conn, w.profile_id))
        measured_by_me = select(comparisons.c.submission_id).where(
            comparisons.c.worker == worker_id, comparisons.c.champion_version == champ.version
        )
        q = (
            select(jobs)
            .where(
                jobs.c.status == "queued",
                jobs.c.profile_id == w.profile_id,
                jobs.c.stage.in_(["screen", "full", "confirm_block"]),
            )
            .order_by(jobs.c.priority_block, jobs.c.priority_index, jobs.c.block_no)
            .with_for_update(skip_locked=True)
            .limit(20)
        )
        for job in conn.execute(q).all():
            if job.stage == "confirm_block" and others_ready > 1:
                # spread blocks across separately provisioned workers: each may take at most its fair share
                mine = (
                    conn.execute(
                        select(func.count()).select_from(
                            measured_by_me.where(comparisons.c.submission_id == job.submission_id).subquery()
                        )
                    ).scalar()
                    or 0
                )
                total_blocks = profile.replacement.blocks
                if mine >= -(-total_blocks // others_ready):  # ceiling division
                    continue
            if job.stage == "full":
                art = conn.execute(
                    select(artifacts.c.trusted_fixture)
                    .join(submissions, submissions.c.artifact_sha256 == artifacts.c.sha256)
                    .where(submissions.c.id == job.submission_id)
                ).scalar()
                if not art and not w.readiness.get("untrusted_code_isolation"):
                    continue
            return _lease(conn, ctx, job, worker_id, profile, champ)
        return None


def _lease(conn: Connection, ctx: AppContext, job, worker_id: str, profile, champ) -> dict:
    lease_s = getattr(profile.deadlines, STAGE_LEASE[job.stage])
    champion_version = job.champion_version if job.stage == "confirm_block" else champ.version
    conn.execute(
        update(jobs)
        .where(jobs.c.id == job.id)
        .values(
            status="leased",
            lease_worker=worker_id,
            lease_expires_at=now() + timedelta(seconds=lease_s),
            attempts=jobs.c.attempts + 1,
            champion_version=champion_version,
            updated_at=now(),
        )
    )
    payload: dict[str, Any] = {
        "job_id": job.id,
        "stage": job.stage,
        "rule_hash": profile.rule_hash(),
        "lease_seconds": lease_s,
        "champion": champion_payload(conn, champ),
        "simulated": ctx.settings.simulated_chain,
    }
    w = conn.execute(select(workers).where(workers.c.id == worker_id)).first()
    if job.submission_id:
        sub = conn.execute(select(submissions).where(submissions.c.id == job.submission_id)).first()
        payload.update(submission_id=sub.id, artifact_sha256=sub.artifact_sha256)
        event = {
            "screen": ("screen_start", S.ADMITTED),
            "full": ("eval_start", S.EVAL_QUEUED),
            "confirm_block": ("confirm_start", S.CONFIRM_QUEUED),
        }[job.stage]
        if sub.state == event[1]:
            transition(conn, ctx, sub.id, event[0])
        payload["seed"] = f"{sub.id}:{job.stage}:{job.attempts + 1}:{champ.version}"
    if job.stage in ("full", "confirm_block"):
        payload["calibration"] = w.readiness.get("calibration", {})
    if job.stage == "confirm_block":
        chain = ctx.chain(conn)
        anchor = chain.finalized_head()
        beacon = DevBeacon()
        scheduled = beacon.round_at(now()) + 1
        cid = new_id("cmp")
        res = resolve_round(beacon, scheduled, cid)
        conn.execute(
            comparisons.insert().values(
                id=cid,
                submission_id=job.submission_id,
                job_id=job.id,
                champion_version=champion_version,
                rule_hash=profile.rule_hash(),
                validator=w.validator,
                worker=worker_id,
                anchor_block=anchor.number,
                beacon_round=res.used_round or scheduled,
                beacon_simulated=True,
                seed=res.seed,
                status="scheduled" if res.seed else "void",
                void_reason=res.void_reason,
            )
        )
        audit.append(
            conn,
            "controller",
            "comparison_scheduled",
            "comparison",
            cid,
            {"anchor_block": anchor.number, "beacon_round": res.used_round, "simulated_beacon": True},
        )
        sub = conn.execute(select(submissions).where(submissions.c.id == job.submission_id)).first()
        payload.update(
            comparison_id=cid,
            seed=res.seed,
            block_no=job.block_no,
            start_k=_start_k(sub.triage_gain_ppm or 0, profile),
        )
    audit.append(conn, worker_id, "job_leased", "job", job.id, {"stage": job.stage})
    return payload


def _start_k(gain_ppm: int, profile) -> int:
    import math

    step = profile.replacement.grid_step_ppm / 1e6
    return max(0, round(math.log(1 + gain_ppm / 1e6) / math.log(1 + step))) if gain_ppm > 0 else 0


def _store_report(
    conn: Connection, ctx: AppContext, job, worker_id: str, kind: str, body: dict, public: dict
) -> str:
    from room_protocol.canonical import record_hash

    rid = new_id("rep")
    h = record_hash(body)
    conn.execute(
        reports.insert().values(
            id=rid,
            submission_id=job.submission_id,
            job_id=job.id,
            kind=kind,
            public_body=public,
            private_body=body,
            hash=h,
            signature=ctx.signer.sign("report", {"hash": h, "job_id": job.id}),
            signer=f"worker:{worker_id}",
            simulated=bool(body.get("simulated", True)),
        )
    )
    return rid


def _operator_failure(conn: Connection, ctx: AppContext, sub_id: str, reason: str) -> None:
    sub = lock_submission(conn, sub_id)
    if sub.state not in {
        s.value
        for s in (
            S.ADMITTED,
            S.SCREENING,
            S.EVAL_QUEUED,
            S.EVALUATING,
            S.CONFIRM_QUEUED,
            S.CONFIRMING,
            S.IN_REVIEW,
            S.READY_FOR_PROMOTION,
        )
    }:
        return
    transition(
        conn,
        ctx,
        sub_id,
        "operator_failure",
        fee_outcome="refund_or_credit",
        outcome_code="operator_failure",
        outcome_summary=reason,
    )
    conn.execute(
        update(jobs)
        .where(jobs.c.submission_id == sub_id, jobs.c.status.in_(["queued", "leased"]))
        .values(status="cancelled", updated_at=now())
    )
    from ..store.schema import quotes

    q = conn.execute(
        select(quotes).where(quotes.c.submission_id == sub_id, quotes.c.status == "paid")
    ).first()
    if q:
        issue_credit(
            conn,
            ctx,
            sub.hotkey,
            q.amount_rao,
            f"operator-side failure: {reason}",
            sub_id,
            f"operator_failure:{sub_id}",
        )
    audit.append(
        conn, "controller", "operator_failure", "submission", sub_id, {"reason": reason}, public=True
    )


def _consume_fee(conn: Connection, ctx: AppContext, sub_id: str) -> None:
    from ..store.schema import quotes

    q = conn.execute(
        select(quotes).where(quotes.c.submission_id == sub_id, quotes.c.status == "paid")
    ).first()
    if q:
        ledger_entry(
            conn, ctx, "fee_consumed", q.amount_rao, sub_id, f"fee_consumed:{sub_id}", q.hotkey, sub_id
        )


def complete(ctx: AppContext, worker_id: str, job_id: str, result: dict) -> dict:
    with tx(ctx.engine) as conn:
        job = conn.execute(select(jobs).where(jobs.c.id == job_id).with_for_update()).first()
        if job is None:
            raise ServiceError("not_found", "job not found", 404)
        if job.status in ("done", "failed", "void", "cancelled"):
            return {"job_id": job_id, "status": job.status, "idempotent": True}
        if job.status != "leased" or job.lease_worker != worker_id:
            raise ServiceError("not_lease_holder", "this worker does not hold the lease", 409)
        if job.lease_expires_at and job.lease_expires_at < now():
            raise ServiceError("lease_expired", "lease expired; result discarded", 409)
        profile = ctx.profile_by_hash(conn, job.rule_hash)
        champ = current_champion(conn, job.profile_id)
        if result.get("infra_failure"):
            return _infra_failure(conn, ctx, job, profile, str(result["infra_failure"]))
        conn.execute(
            update(jobs)
            .where(jobs.c.id == job_id)
            .values(
                status="done",
                result=result,
                gpu_centi_used=int(result.get("gpu_centi", 0)),
                updated_at=now(),
                simulated=bool(result.get("simulated", True)),
            )
        )
        if job.stage == "calibration":
            w = conn.execute(select(workers).where(workers.c.id == worker_id)).first()
            readiness = dict(w.readiness)
            readiness["calibration"] = {
                k: result[k] for k in ("capacity_milli_rps", "tight_capacity_milli_rps", "flag")
            }
            conn.execute(
                update(workers)
                .where(workers.c.id == worker_id)
                .values(
                    calibrated_champion_version=job.champion_version, calibrated_at=now(), readiness=readiness
                )
            )
            if (
                champ.version == job.champion_version
                and not champ.capacity_milli_rps
                and result["capacity_milli_rps"]
            ):
                conn.execute(
                    update(champions)
                    .where(champions.c.profile_id == job.profile_id, champions.c.version == champ.version)
                    .values(capacity_milli_rps=result["capacity_milli_rps"])
                )
            audit.append(
                conn,
                worker_id,
                "calibrated",
                "worker",
                worker_id,
                {
                    "champion_version": job.champion_version,
                    "capacity_milli_rps": result["capacity_milli_rps"],
                },
            )
            return {"job_id": job_id, "status": "done"}
        sub = lock_submission(conn, job.submission_id)
        if job.stage == "screen":
            _store_report(
                conn,
                ctx,
                job,
                worker_id,
                "screen",
                result,
                {"decisive_failure": result.get("decisive_failure"), "checks": result.get("checks", [])},
            )
            if result.get("decisive_failure"):
                transition(
                    conn,
                    ctx,
                    sub.id,
                    "screen_decisive_fail",
                    fee_outcome="consumed",
                    outcome_code=f"screen_{result['decisive_failure']}",
                    outcome_summary=result.get("explanation"),
                )
                _consume_fee(conn, ctx, sub.id)
            else:
                transition(conn, ctx, sub.id, "screen_pass")
                conn.execute(
                    jobs.insert().values(
                        id=new_id("job"),
                        submission_id=sub.id,
                        profile_id=sub.profile_id,
                        stage="full",
                        priority_block=sub.admission_block,
                        priority_index=sub.admission_index,
                        rule_hash=sub.rule_hash,
                    )
                )
            audit.append(
                conn,
                worker_id,
                "screen_done",
                "submission",
                sub.id,
                {"decisive_failure": result.get("decisive_failure")},
                public=True,
            )
        elif job.stage == "full":
            if job.champion_version != champ.version:
                return _rebase_full(conn, ctx, job, sub, profile, champ)
            _store_report(conn, ctx, job, worker_id, "full", result, _public_full(result))
            potential = bool(result.get("potential_winner"))
            if potential:
                transition(
                    conn,
                    ctx,
                    sub.id,
                    "eval_potential",
                    triage_gain_ppm=result.get("triage_gain_ppm"),
                    compared_champion_version=champ.version,
                    compared_rule_hash=profile.rule_hash(),
                )
                _create_blocks(conn, sub, profile, champ.version)
            else:
                transition(
                    conn,
                    ctx,
                    sub.id,
                    "eval_not_potential",
                    triage_gain_ppm=result.get("triage_gain_ppm"),
                    compared_champion_version=champ.version,
                    compared_rule_hash=profile.rule_hash(),
                    fee_outcome="consumed",
                    outcome_code="not_potential_winner",
                    outcome_summary=result.get("summary"),
                )
                _consume_fee(conn, ctx, sub.id)
            audit.append(
                conn,
                worker_id,
                "full_evaluation_done",
                "submission",
                sub.id,
                {"potential_winner": potential, "triage_gain_ppm": result.get("triage_gain_ppm")},
                public=True,
            )
        elif job.stage == "confirm_block":
            _complete_block(conn, ctx, job, sub, profile, champ, worker_id, result)
        return {"job_id": job_id, "status": "done"}


def _public_full(result: dict) -> dict:
    keep = (
        "capacity",
        "gates",
        "failed_gates",
        "triage_gain_ppm",
        "potential_winner",
        "summary",
        "p_ctl",
        "p_live",
        "pooled_gate_reasons",
    )
    out = {k: result.get(k) for k in keep if k in result}
    q = result.get("quality", {})
    out["quality"] = {
        "passed": q.get("passed"),
        "reasons": q.get("reasons"),
        "accuracy_bp": q.get("accuracy_bp"),
    }
    me = result.get("memory_evidence")
    if me:
        out["memory_evidence"] = me
    return out


def _create_blocks(conn: Connection, sub, profile, champion_version: int) -> None:
    for b in range(profile.replacement.blocks):
        conn.execute(
            jobs.insert().values(
                id=new_id("job"),
                submission_id=sub.id,
                profile_id=sub.profile_id,
                stage="confirm_block",
                block_no=b,
                priority_block=sub.admission_block,
                priority_index=sub.admission_index,
                champion_version=champion_version,
                rule_hash=sub.rule_hash,
            )
        )


def _rebase_full(conn: Connection, ctx: AppContext, job, sub, profile, champ) -> dict:
    if sub.rebases_used >= profile.deadlines.max_rebases:
        _operator_failure(conn, ctx, sub.id, "maximum automatic rebases reached after champion changes")
        return {"job_id": job.id, "status": "done", "rebase": "limit"}
    transition(conn, ctx, sub.id, "rebase", rebases_used=sub.rebases_used + 1)
    conn.execute(
        jobs.insert().values(
            id=new_id("job"),
            submission_id=sub.id,
            profile_id=sub.profile_id,
            stage="full",
            priority_block=sub.admission_block,
            priority_index=sub.admission_index,
            rule_hash=sub.rule_hash,
        )
    )
    audit.append(
        conn,
        "controller",
        "rebased",
        "submission",
        sub.id,
        {"reason": "champion changed during full evaluation", "new_champion_version": champ.version},
        public=True,
    )
    return {"job_id": job.id, "status": "done", "rebase": True}


def _complete_block(
    conn: Connection, ctx: AppContext, job, sub, profile, champ, worker_id: str, result: dict
) -> None:
    cmp_row = conn.execute(
        select(comparisons).where(comparisons.c.job_id == job.id, comparisons.c.status == "scheduled")
    ).first()
    if cmp_row is None or result.get("comparison_id") != cmp_row.id:
        raise ServiceError("bad_comparison", "result does not match the scheduled comparison", 409)
    conn.execute(
        update(comparisons)
        .where(comparisons.c.id == cmp_row.id)
        .values(
            status="measured",
            challenger_milli_rps=int(result["challenger_milli_rps"]),
            champion_milli_rps=int(result["champion_milli_rps"]),
            report_hash=result.get("report_hash"),
        )
    )
    _store_report(
        conn,
        ctx,
        job,
        worker_id,
        "confirm_block",
        result,
        {
            k: result.get(k)
            for k in ("challenger_milli_rps", "champion_milli_rps", "arm_order", "report_hash")
        },
    )
    if job.champion_version != champ.version or sub.state not in (S.CONFIRMING, S.CONFIRM_QUEUED):
        return  # superseded evidence; rebase path already scheduled fresh blocks
    open_blocks = conn.execute(
        select(func.count())
        .select_from(jobs)
        .where(
            jobs.c.submission_id == sub.id,
            jobs.c.stage == "confirm_block",
            jobs.c.champion_version == champ.version,
            jobs.c.status.in_(["queued", "leased"]),
        )
    ).scalar()
    if open_blocks:
        return
    rows = conn.execute(
        select(comparisons, validators.c.independence_group)
        .join(validators, validators.c.hotkey == comparisons.c.validator)
        .where(
            comparisons.c.submission_id == sub.id,
            comparisons.c.champion_version == champ.version,
            comparisons.c.status == "measured",
        )
    ).all()
    blocks = [
        Block(r.id, r.champion_version, r.challenger_milli_rps, r.champion_milli_rps, r.validator, r.worker)
        for r in rows
    ]
    bound = replacement_bound(blocks, profile.replacement, champ.version)
    distinct_workers = {r.worker for r in rows}
    groups = {r.independence_group for r in rows}
    reasons = list(bound.reasons)
    if profile.bootstrap.mode == "mainnet":
        quorum_ok = len(groups) >= profile.bootstrap.quorum_validators_after_sunset
    else:
        quorum_ok = len(distinct_workers) >= 2
    if not quorum_ok:
        reasons.append("blocks did not come from enough separately provisioned workers/validators")
    summary = {
        "n": bound.n,
        "mean_gain_ppm": int(bound.mean_gain * 1e6),
        "lower_bound_gain_ppm": int(bound.lower_gain * 1e6) if bound.lower_gain > -1 else None,
        "sd_used_ppm": int(bound.sd_used * 1e6),
        "workers": sorted(distinct_workers),
        "independence_groups": sorted(groups),
        "quorum_ok": quorum_ok,
        "reasons": reasons,
    }
    audit.append(conn, "controller", "confirmation_evaluated", "submission", sub.id, summary, public=True)
    if bound.passes_margin and quorum_ok:
        transition(conn, ctx, sub.id, "confirm_pass", bound_gain_ppm=int(bound.lower_gain * 1e6))
        conn.execute(
            reviews.insert().values(
                id=new_id("rev"),
                submission_id=sub.id,
                reviewer="unassigned",
                criteria=review_criteria(),
                due_at=now() + timedelta(seconds=profile.deadlines.review_s),
            )
        )
    elif not quorum_ok and sub.quorum_reschedules < profile.deadlines.max_quorum_reschedules:
        conn.execute(
            update(submissions)
            .where(submissions.c.id == sub.id)
            .values(quorum_reschedules=sub.quorum_reschedules + 1)
        )
        _create_blocks(conn, sub, profile, champ.version)
    elif not quorum_ok:
        _operator_failure(conn, ctx, sub.id, "confirmation quorum could not be assembled")
    else:
        transition(
            conn,
            ctx,
            sub.id,
            "confirm_fail",
            bound_gain_ppm=int(bound.lower_gain * 1e6) if bound.lower_gain > -1 else None,
            fee_outcome="consumed",
            outcome_code="margin_not_cleared",
            outcome_summary="; ".join(reasons),
        )
        _consume_fee(conn, ctx, sub.id)


def review_criteria() -> list[dict]:
    return [
        {"id": c, "title": t}
        for c, t in [
            ("license", "License compatibility and complete attribution"),
            ("reproducible_build", "Build reproduces from the frozen artifact"),
            ("adaptivity", "No forbidden benchmark-recognition adaptivity"),
            ("security", "Security scans and fuzzing clean"),
            ("native_review", "Independent review of native code"),
            ("soak", "6-hour soak at 90% of confirmed capacity without errors above the gate"),
            ("mechanism", "Declared memory mechanism confirmed in the code"),
        ]
    ]


def _infra_failure(conn: Connection, ctx: AppContext, job, profile, reason: str) -> dict:
    if job.attempts <= profile.deadlines.max_lease_retries:
        conn.execute(
            update(jobs)
            .where(jobs.c.id == job.id)
            .values(
                status="queued",
                lease_worker=None if job.stage != "calibration" else job.lease_worker,
                lease_expires_at=None,
                updated_at=now(),
            )
        )
        if job.submission_id:
            sub = lock_submission(conn, job.submission_id)
            if sub.state in (S.SCREENING, S.EVALUATING, S.CONFIRMING) and job.stage != "confirm_block":
                transition(conn, ctx, sub.id, "lease_expired")
        conn.execute(
            update(comparisons)
            .where(comparisons.c.job_id == job.id, comparisons.c.status == "scheduled")
            .values(status="void", void_reason=f"infrastructure: {reason}")
        )
        audit.append(
            conn, "controller", "job_requeued", "job", job.id, {"reason": reason, "priority_kept": True}
        )
        return {"job_id": job.id, "status": "requeued"}
    conn.execute(update(jobs).where(jobs.c.id == job.id).values(status="failed", updated_at=now()))
    conn.execute(
        update(comparisons)
        .where(comparisons.c.job_id == job.id, comparisons.c.status == "scheduled")
        .values(status="void", void_reason=f"infrastructure: {reason}")
    )
    if job.submission_id:
        _operator_failure(conn, ctx, job.submission_id, f"repeated infrastructure failure: {reason}")
    return {"job_id": job.id, "status": "failed"}


def expire_leases(conn: Connection, ctx: AppContext) -> int:
    n = 0
    for job in conn.execute(
        select(jobs)
        .where(jobs.c.status == "leased", jobs.c.lease_expires_at < now())
        .with_for_update(skip_locked=True)
    ).all():
        profile = ctx.profile_by_hash(conn, job.rule_hash)
        _infra_failure(conn, ctx, job, profile, "lease expired")
        n += 1
    return n


def cancel_stale_blocks(conn: Connection, sub_id: str, keep_version: int) -> None:
    conn.execute(
        update(jobs)
        .where(
            and_(
                jobs.c.submission_id == sub_id,
                jobs.c.stage == "confirm_block",
                jobs.c.champion_version != keep_version,
                jobs.c.status.in_(["queued", "leased"]),
            )
        )
        .values(status="cancelled")
    )
