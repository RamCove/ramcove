"""Leases, job results and stage transitions (Sections 6.4, 7.8).

Dispatch order = oldest admission key first among compatible queued jobs. Completion order is free.
Promotion order is enforced separately in settlement.py.

Each worker holds the current champion's fixed score, measured once when that champion was crowned. A
challenger's evaluation is set against that score: one reading, a second only when the first is close.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from ramcove_chain.beacon import DevBeacon, resolve_round
from ramcove_protocol.reservation import remaining_envelope
from ramcove_protocol.scoring import Reading, gain_against_later_champion
from ramcove_protocol.state import PAID_ACTIVE, S
from sqlalchemy import Connection, select, update

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
from . import banks
from .accounting import issue_credit, ledger_entry
from .context import AppContext, ServiceError
from .intake import _set_state, lock_submission

STAGE_LEASE = {
    "screen": "lease_screen_s",
    "full": "lease_full_s",
    "reproduce": "lease_reproduce_s",
    "calibration": "lease_full_s",
}
# a winner whose patch touches native code goes to a person before promotion
DEFAULT_START_MILLI_RPS = 500  # the tuned baseline's first search, before any score exists
NATIVE_SUFFIXES = (".cu", ".cuh", ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".pyx", ".so")


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
        .values(reserved_centi=remaining_envelope(S(sub.state), profile.envelope))
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
        # the champion's score on this worker: measured once per champion, never again
        stale_cal = w.calibrated_champion_version != champ.version or w.calibrated_at is None
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
        q = (
            select(jobs)
            .where(
                jobs.c.status == "queued",
                jobs.c.profile_id == w.profile_id,
                jobs.c.stage.in_(["screen", "full", "reproduce"]),
            )
            .order_by(jobs.c.priority_block, jobs.c.priority_index)
            .with_for_update(skip_locked=True)
            .limit(20)
        )
        my_group = conn.execute(
            select(validators.c.independence_group).where(validators.c.hotkey == w.validator)
        ).scalar()
        for job in conn.execute(q).all():
            if job.stage == "reproduce":
                # a reproduction must come from a validator with no shared operator
                measured_by = {
                    g
                    for (g,) in conn.execute(
                        select(validators.c.independence_group)
                        .join(comparisons, comparisons.c.validator == validators.c.hotkey)
                        .where(comparisons.c.submission_id == job.submission_id)
                    ).all()
                }
                if my_group in measured_by:
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
    champion_version = champ.version
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
        # the owner's question bank for the current period: the same questions for every job in it
        "bank": banks.bank_for_job(conn, ctx, profile),
    }
    w = conn.execute(select(workers).where(workers.c.id == worker_id)).first()
    # the champion's fixed score and its answers to the current bank, both kept per worker
    payload["calibration"] = w.readiness.get("calibration", {})
    if job.stage == "calibration":
        # search from the champion's known capacity (its winning measurement, or another worker's score), so
        # the grid brackets the real value instead of starting from an arbitrary rate
        payload["start_milli_rps"] = champ.capacity_milli_rps or DEFAULT_START_MILLI_RPS
    if job.submission_id:
        sub = conn.execute(select(submissions).where(submissions.c.id == job.submission_id)).first()
        payload.update(submission_id=sub.id, artifact_sha256=sub.artifact_sha256)
        event = {
            "screen": ("screen_start", S.ADMITTED),
            "full": ("eval_start", S.EVAL_QUEUED),
            "reproduce": ("reproduce_start", S.REPRODUCE_QUEUED),
        }[job.stage]
        if sub.state == event[1]:
            transition(conn, ctx, sub.id, event[0])
        payload["seed"] = f"{sub.id}:{job.stage}:{job.attempts + 1}:{champ.version}"
    if job.stage in ("full", "reproduce"):
        # promotion evidence: the reading's traffic also mixes in a beacon round nobody can know in advance
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
        payload.update(comparison_id=cid, seed=res.seed or payload["seed"])
    audit.append(conn, worker_id, "job_leased", "job", job.id, {"stage": job.stage})
    return payload


def _store_report(
    conn: Connection, ctx: AppContext, job, worker_id: str, kind: str, body: dict, public: dict
) -> str:
    from ramcove_protocol.canonical import record_hash

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
    if sub.state not in {s.value for s in PAID_ACTIVE}:
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
                k: result[k]
                for k in ("capacity_milli_rps", "tight_capacity_milli_rps", "flag", "pctl", "answers")
                if k in result
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
                and not champ.capacity_measured
                and result["capacity_milli_rps"]
            ):
                # the first worker to measure a new champion replaces the estimate shown publicly
                conn.execute(
                    update(champions)
                    .where(champions.c.profile_id == job.profile_id, champions.c.version == champ.version)
                    .values(capacity_milli_rps=result["capacity_milli_rps"], capacity_measured=True)
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
            _complete_evaluation(conn, ctx, job, sub, profile, champ, worker_id, result)
        elif job.stage == "reproduce":
            _complete_reproduction(conn, ctx, job, sub, profile, champ, worker_id, result)
        return {"job_id": job_id, "status": "done"}


def _public_full(result: dict) -> dict:
    keep = (
        "readings",
        "decision",
        "gates",
        "failed_gates",
        "gain_ppm",
        "winner",
        "summary",
        "p_ctl",
        "p_live",
        "soak",
        "band_attainment_reasons",
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


def promoted_gains_since(conn: Connection, profile_id: str, measured_version: int, current_version: int):
    """Gains of the champions crowned after ``measured_version``, oldest first, so a measured gain can be set
    against the current champion without measuring again. ``None`` if a rollback happened in between: a
    restored stack has no gain relative to the one it replaced, so that evaluation runs again."""
    rows = conn.execute(
        select(champions)
        .where(
            champions.c.profile_id == profile_id,
            champions.c.version > measured_version,
            champions.c.version <= current_version,
        )
        .order_by(champions.c.version)
    ).all()
    gains = []
    for r in rows:
        if (r.attribution or {}).get("restored_from_version") is not None or r.bound_gain_ppm is None:
            return None
        gains.append(r.bound_gain_ppm)
    return gains


def requeue_evaluation(conn: Connection, ctx: AppContext, sub, reason: str) -> None:
    """Evaluate again against the current champion, same admission key, no new fee (after a rollback)."""
    conn.execute(
        update(jobs)
        .where(jobs.c.submission_id == sub.id, jobs.c.status.in_(["queued", "leased"]))
        .values(status="cancelled", updated_at=now())
    )
    transition(conn, ctx, sub.id, "requeue", compared_champion_version=None, ready_since=None)
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
        "evaluation_requeued",
        "submission",
        sub.id,
        {"reason": reason, "fee": "no new fee", "priority": "kept"},
        public=True,
    )


def automatic_flags(conn: Connection, sub, result: dict) -> list[str]:
    """What sends a winner to a person before promotion; otherwise promotion is automatic."""
    flags = list(result.get("review_flags") or [])
    art = conn.execute(select(artifacts).where(artifacts.c.sha256 == sub.artifact_sha256)).first()
    if art is not None:
        if any(str(p).lower().endswith(NATIVE_SUFFIXES) for p in (art.changed_paths or [])):
            flags.append("native_code")
        if (art.manifest or {}).get("third_party"):
            flags.append("third_party_components")
    return sorted(set(flags))


def _record_readings(conn: Connection, job, readings: list[dict], cmp_id: str | None) -> None:
    cmp_row = conn.execute(select(comparisons).where(comparisons.c.id == cmp_id)).first() if cmp_id else None
    if cmp_row is None or cmp_row.job_id != job.id or cmp_row.status != "scheduled":
        raise ServiceError("bad_comparison", "result does not match the scheduled measurement", 409)
    for n, r in enumerate(readings):
        values = dict(
            status="measured",
            challenger_milli_rps=int(r["challenger_milli_rps"]),
            champion_milli_rps=int(r["champion_milli_rps"]),
        )
        if n == 0:
            conn.execute(update(comparisons).where(comparisons.c.id == cmp_row.id).values(**values))
        else:
            conn.execute(
                comparisons.insert().values(
                    id=new_id("cmp"),
                    submission_id=cmp_row.submission_id,
                    job_id=job.id,
                    champion_version=cmp_row.champion_version,
                    rule_hash=cmp_row.rule_hash,
                    validator=cmp_row.validator,
                    worker=cmp_row.worker,
                    anchor_block=cmp_row.anchor_block,
                    beacon_round=cmp_row.beacon_round,
                    beacon_simulated=cmp_row.beacon_simulated,
                    seed=f"{cmp_row.seed}:reading{n}",
                    **values,
                )
            )
    if not readings:
        conn.execute(
            update(comparisons)
            .where(comparisons.c.id == cmp_row.id)
            .values(status="void", void_reason="quality failed before any capacity reading")
        )


def _win(
    conn: Connection, ctx: AppContext, sub, profile, champ, gain_ppm: int, result: dict, via: str
) -> None:
    """A challenger cleared the rule: automatic promotion unless a check flags it for a person."""
    flags = automatic_flags(conn, sub, result)
    common = dict(
        bound_gain_ppm=gain_ppm,
        compared_champion_version=champ.version,
        compared_rule_hash=profile.rule_hash(),
    )
    if via == "evaluation" and profile.bootstrap.mode == "mainnet":
        transition(conn, ctx, sub.id, "eval_win_reproduce", **common)
        conn.execute(
            jobs.insert().values(
                id=new_id("job"),
                submission_id=sub.id,
                profile_id=sub.profile_id,
                stage="reproduce",
                priority_block=sub.admission_block,
                priority_index=sub.admission_index,
                rule_hash=sub.rule_hash,
            )
        )
        return
    if flags:
        transition(
            conn,
            ctx,
            sub.id,
            "eval_win_flagged" if via == "evaluation" else "reproduce_pass_flagged",
            **common,
        )
        conn.execute(
            reviews.insert().values(
                id=new_id("rev"),
                submission_id=sub.id,
                reviewer="unassigned",
                criteria=[{**c, "flagged": c["id"] in _criteria_for(flags)} for c in review_criteria()],
                reasons=None,
                due_at=now() + timedelta(seconds=profile.deadlines.review_s),
            )
        )
        audit.append(
            conn, "controller", "flagged_for_review", "submission", sub.id, {"flags": flags}, public=True
        )
    else:
        transition(
            conn,
            ctx,
            sub.id,
            "eval_win" if via == "evaluation" else "reproduce_pass",
            ready_since=now(),
            **common,
        )
        audit.append(
            conn,
            "controller",
            "cleared_for_promotion",
            "submission",
            sub.id,
            {"gain_ppm": gain_ppm},
            public=True,
        )


def _criteria_for(flags: list[str]) -> set[str]:
    by_flag = {
        "native_code": "native_review",
        "third_party_components": "license",
        "security_scan": "security",
    }
    return {by_flag.get(f, f) for f in flags}


def _lose(conn: Connection, ctx: AppContext, sub, event: str, code: str, summary: str, **values) -> None:
    transition(
        conn,
        ctx,
        sub.id,
        event,
        fee_outcome="consumed",
        outcome_code=code,
        outcome_summary=summary[:500],
        **values,
    )
    _consume_fee(conn, ctx, sub.id)


def _store_answers(conn: Connection, job, worker_id: str, result: dict) -> None:
    """The first evaluation after a bank rotates has the champion answer the new bank; keep those answers
    with the worker's fixed score so later evaluations in the period do not ask the champion again."""
    answers = result.get("champion_answers")
    if not answers:
        return
    w = conn.execute(select(workers).where(workers.c.id == worker_id).with_for_update()).first()
    if w is None or w.calibrated_champion_version != job.champion_version:
        return
    readiness = dict(w.readiness)
    readiness["calibration"] = {**readiness.get("calibration", {}), "answers": answers}
    conn.execute(update(workers).where(workers.c.id == worker_id).values(readiness=readiness))


def _complete_evaluation(
    conn: Connection, ctx: AppContext, job, sub, profile, champ, worker_id: str, result: dict
) -> None:
    readings = result.get("readings") or []
    _record_readings(conn, job, readings, result.get("comparison_id"))
    _store_answers(conn, job, worker_id, result)
    _store_report(conn, ctx, job, worker_id, "full", result, _public_full(result))
    first = readings[0] if readings else None
    first_gain = (
        Reading("", 0, int(first["challenger_milli_rps"]), int(first["champion_milli_rps"]), "").gain_ppm()
        if first and first["champion_milli_rps"]
        else None
    )
    gain = result.get("gain_ppm")
    measured = dict(
        first_gain_ppm=first_gain,
        compared_champion_version=job.champion_version,
        compared_rule_hash=profile.rule_hash(),
    )
    audit.append(
        conn,
        worker_id,
        "evaluation_done",
        "submission",
        sub.id,
        {"winner": bool(result.get("winner")), "gain_ppm": gain, "readings": len(readings)},
        public=True,
    )
    if not result.get("winner"):
        failed = result.get("failed_gates") or []
        code = (
            "quality_failed"
            if "offline_quality" in failed
            else "winner_check_failed"
            if (result.get("decision") or {}).get("outcome") == "win"
            else "margin_not_cleared"
        )
        _lose(
            conn,
            ctx,
            sub,
            "eval_lose",
            code,
            result.get("summary") or "did not clear the rule",
            bound_gain_ppm=gain,
            **measured,
        )
        return
    if job.champion_version != champ.version:
        # another challenger was crowned while this one was being measured
        gains = promoted_gains_since(conn, sub.profile_id, job.champion_version, champ.version)
        if gains is None:
            requeue_evaluation(conn, ctx, sub, "the champion was rolled back during this evaluation")
            return
        gain = gain_against_later_champion(gain, gains)
        if gain <= profile.replacement.delta_ppm:
            _lose(
                conn,
                ctx,
                sub,
                "eval_lose",
                "champion_changed",
                f"A new champion (version {champ.version}) was crowned first. Over it the gain is "
                f"{gain / 1e4:.1f}%, which does not exceed the {profile.replacement.delta_ppm / 1e4:.0f}% margin.",
                bound_gain_ppm=gain,
                **measured,
            )
            return
    conn.execute(update(submissions).where(submissions.c.id == sub.id).values(first_gain_ppm=first_gain))
    _win(conn, ctx, sub, profile, champ, gain, result, "evaluation")


def _complete_reproduction(
    conn: Connection, ctx: AppContext, job, sub, profile, champ, worker_id: str, result: dict
) -> None:
    readings = result.get("readings") or []
    _record_readings(conn, job, readings, result.get("comparison_id"))
    _store_report(
        conn,
        ctx,
        job,
        worker_id,
        "reproduce",
        result,
        {k: result.get(k) for k in ("readings", "gain_ppm", "passed")},
    )
    gain = int(result.get("gain_ppm") or -1_000_000)
    if job.champion_version != champ.version:
        gains = promoted_gains_since(conn, sub.profile_id, job.champion_version, champ.version)
        if gains is None:
            requeue_evaluation(conn, ctx, sub, "the champion was rolled back during reproduction")
            return
        gain = gain_against_later_champion(gain, gains)
    if gain > profile.replacement.delta_ppm:
        _win(conn, ctx, sub, profile, champ, min(gain, sub.bound_gain_ppm or gain), result, "reproduction")
    else:
        _lose(
            conn,
            ctx,
            sub,
            "reproduce_fail",
            "not_reproduced",
            f"An independent validator measured {gain / 1e4:.1f}% over the champion's score, which does not "
            f"exceed the {profile.replacement.delta_ppm / 1e4:.0f}% margin.",
        )


def review_criteria() -> list[dict]:
    return [
        {"id": c, "title": t}
        for c, t in [
            ("license", "License compatibility and complete attribution"),
            ("reproducible_build", "Build reproduces from the frozen artifact"),
            ("adaptivity", "No forbidden benchmark-recognition adaptivity"),
            ("security", "Security scans and fuzzing clean"),
            ("native_review", "Independent review of native code"),
            ("soak", "1-hour soak at 90% of measured capacity without errors above the gate"),
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
            if sub.state in (S.SCREENING, S.EVALUATING, S.REPRODUCING):
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
