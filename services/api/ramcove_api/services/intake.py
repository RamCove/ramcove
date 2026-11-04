"""Free preflight, free admission to the queue and the free waiting list.

Submitting costs nothing. Evaluation capacity is what limits the queue: a submission that passes the free
checks is admitted when capacity is free and waits on the waiting list otherwise.
"""

from __future__ import annotations

from typing import Any

from ramcove_protocol.canonical import record_hash, signing_payload
from ramcove_protocol.preflight import run_preflight
from ramcove_protocol.reservation import can_admit
from ramcove_protocol.state import S, next_state
from sqlalchemy import Connection, func, select, update
from sqlalchemy.exc import IntegrityError

from ..signing import verify_sr25519
from ..store import audit
from ..store.db import advisory_lock, new_id, now, retry_on_contention, support_ref, tx
from ..store.schema import artifacts, jobs, submissions
from .context import AppContext, ServiceError, load_trusted_fixtures


def artifact_signing_body(sha256: str, profile_id: str, version: str, hotkey: str) -> dict[str, Any]:
    return {"artifact_sha256": sha256, "profile_id": profile_id, "profile_version": version, "hotkey": hotkey}


def _set_state(conn: Connection, sub_id: str, current: str, event: str, **values: Any) -> str:
    new = next_state(current, event)
    res = conn.execute(
        update(submissions)
        .where(submissions.c.id == sub_id, submissions.c.state == current)
        .values(state=new.value, updated_at=now(), row_version=submissions.c.row_version + 1, **values)
    )
    if res.rowcount != 1:
        raise ServiceError("conflict", "the submission changed concurrently; refresh and retry", 409)
    return new.value


def lock_submission(conn: Connection, sub_id: str):
    row = conn.execute(select(submissions).where(submissions.c.id == sub_id).with_for_update()).first()
    if row is None:
        raise ServiceError("not_found", "submission not found", 404)
    return row


def preflight(ctx: AppContext, hotkey: str, data: bytes, signature_hex: str) -> dict[str, Any]:
    with tx(ctx.engine) as conn:
        profile = ctx.profile(conn)
        known = set()
        for r in conn.execute(select(artifacts.c.sha256, artifacts.c.normalized_patch_sha256)):
            known.update({r.sha256, r.normalized_patch_sha256})
        from ramcove_protocol.canonical import sha256_hex

        sha = sha256_hex(data)
        try:
            sig = bytes.fromhex(signature_hex.removeprefix("0x"))
        except ValueError:
            sig = b""
        sig_ok = verify_sr25519(
            hotkey,
            signing_payload(
                "artifact",
                ctx.settings.network,
                artifact_signing_body(sha, profile.profile_id, profile.version, hotkey),
            ),
            sig,
        )
        result = run_preflight(data, profile, known, signature_ok=sig_ok)
        if result.manifest and result.manifest.hotkey != hotkey:
            result.fail("hotkey_mismatch", "manifest hotkey differs from the signed-in hotkey")
        # an excluded hotkey is refused here, in the free checks, before it can take a queue place
        excluded = ctx.setting(conn, "excluded_hotkeys", {}) or {}
        if hotkey in (excluded.get("hotkeys") or {}):
            result.fail(
                "hotkey_excluded",
                f"this hotkey is excluded from the competition: {excluded['hotkeys'][hotkey]}",
            )
        public = {
            "ok": result.ok,
            "artifact_sha256": result.artifact_sha256,
            "errors": result.errors,
            "changed_paths": result.changed_paths,
            "free": True,
            "checked": [
                "archive safety and size",
                "manifest format",
                "hotkey signature",
                "profile version",
                "allowed and forbidden paths",
                "declared licenses",
                "exact and cosmetic duplicates",
            ],
        }
        if not result.ok:
            audit.append(
                conn,
                hotkey,
                "preflight_rejected",
                "artifact",
                result.artifact_sha256,
                {"errors": [e["code"] for e in result.errors]},
            )
            return public
        assert result.manifest is not None
        fixtures = load_trusted_fixtures()
        fixture = fixtures.get(result.normalized_patch_sha256 or "")
        key = ctx.artifacts.put(result.artifact_sha256, data)
        conn.execute(
            artifacts.insert().values(
                sha256=result.artifact_sha256,
                normalized_patch_sha256=result.normalized_patch_sha256,
                size_bytes=len(data),
                storage_key=key,
                uploader=hotkey,
                manifest=result.manifest.model_dump(mode="json", by_alias=True),
                changed_paths=result.changed_paths,
                trusted_fixture=fixture["name"] if fixture else None,
            )
        )
        sub_id = new_id("sub")
        try:
            with conn.begin_nested():
                conn.execute(
                    submissions.insert().values(
                        id=sub_id,
                        profile_id=profile.profile_id,
                        profile_version=profile.version,
                        rule_hash=profile.rule_hash(),
                        hotkey=hotkey,
                        lineage=result.manifest.lineage,
                        artifact_sha256=result.artifact_sha256,
                        state=S.PREFLIGHT_PASSED.value,
                        support_ref=support_ref(),
                    )
                )
        except IntegrityError as e:
            raise ServiceError(
                "active_limit",
                "this hotkey or lineage already has an active submission; finish or withdraw it first",
                409,
            ) from e
        audit.append(
            conn,
            hotkey,
            "preflight_passed",
            "submission",
            sub_id,
            {"artifact_sha256": result.artifact_sha256, "trusted_fixture": bool(fixture)},
        )
        public.update({"submission_id": sub_id, "trusted_fixture": fixture["name"] if fixture else None})
        return public


@retry_on_contention()
def admit(ctx: AppContext, sub_id: str, hotkey: str) -> dict[str, Any]:
    """Admit a submission that passed the free checks to the queue, free of charge, or place it on the free
    waiting list while evaluation capacity is fully reserved. Joining the queue needs a hotkey registered on
    the subnet; the free checks do not."""
    with tx(ctx.engine) as conn:
        sub = lock_submission(conn, sub_id)
        if sub.hotkey != hotkey:
            raise ServiceError("forbidden", "only the submitting hotkey can join the queue", 403)
        if sub.state not in (S.PREFLIGHT_PASSED, S.INVITED, S.WAITLISTED):
            raise ServiceError("bad_state", f"cannot join the queue from state {sub.state}", 409)
        if sub.state == S.WAITLISTED:
            return {
                "status": "waitlisted",
                "message": "you are on the free waiting list; you will be invited",
            }
        profile = ctx.profile(conn, sub.profile_id)
        if profile.rule_hash() != sub.rule_hash:
            raise ServiceError("profile_changed", "the profile version changed; run preflight again", 409)
        chain = ctx.chain(conn)
        _, uids = chain.hotkey_uid_map(ctx.settings.netuid)
        if hotkey not in uids:
            raise ServiceError(
                "not_registered",
                "joining the queue needs a hotkey registered on this subnet (the free checks do not); "
                "register it and try again",
                409,
            )
        advisory_lock(conn, f"capacity:{profile.profile_id}")
        art = conn.execute(select(artifacts).where(artifacts.c.sha256 == sub.artifact_sha256)).first()
        plan = ctx.capacity_plan(conn, profile, trusted_fixture=bool(art.trusted_fixture))
        paused = bool(ctx.setting(conn, "intake_paused", {"paused": False}).get("paused"))
        check = can_admit(ctx.committed_centi(conn, profile.profile_id), profile.envelope, plan, paused)
        if not check.allowed:
            if sub.state == S.PREFLIGHT_PASSED:
                _set_state(conn, sub_id, sub.state, "waitlist", waitlisted_at=now())
            elif sub.state == S.INVITED:
                _set_state(
                    conn, sub_id, sub.state, "invitation_missed", waitlisted_at=now(), invited_until=None
                )
            audit.append(conn, hotkey, "waitlisted", "submission", sub_id, {"reason": check.reason})
            return {"status": "waitlisted", "message": check.reason, "capacity": check.__dict__}
        # the admission key orders the queue: the finalized block at admission, then the order within it
        advisory_lock(conn, "admission_key")
        block = chain.finalized_head().number
        index = conn.execute(
            select(func.count()).select_from(submissions).where(submissions.c.admission_block == block)
        ).scalar()
        admitted_at = now()
        _set_state(
            conn,
            sub_id,
            sub.state,
            "admit",
            reserved_centi=check.requested_centi,
            invited_until=None,
            admission_block=block,
            admission_index=index,
            admitted_at=admitted_at,
        )
        conn.execute(
            jobs.insert().values(
                id=new_id("job"),
                submission_id=sub_id,
                profile_id=sub.profile_id,
                stage="screen",
                priority_block=block,
                priority_index=index,
                rule_hash=sub.rule_hash,
            )
        )
        body = {
            "schema": "ramcove.admission/1",
            "submission_id": sub_id,
            "network": ctx.settings.network,
            "genesis_hash": ctx.network_identity.genesis_hash,
            "hotkey": hotkey,
            "artifact_sha256": sub.artifact_sha256,
            "profile_id": profile.profile_id,
            "profile_version": profile.version,
            "rule_hash": sub.rule_hash,
            "admission_key": [block, index],
            "admitted_at": admitted_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        audit.append(
            conn,
            "system",
            "admitted",
            "submission",
            sub_id,
            {"admission_key": [block, index], "admission_hash": record_hash(body)},
            public=True,
        )
        return {
            "status": "admitted",
            "admission": body,
            "signature": ctx.signer.sign("admission", body),
            "signer": ctx.signer.address,
        }


def withdraw(ctx: AppContext, sub_id: str, hotkey: str, reason: str) -> dict[str, Any]:
    """Withdraw at any time before promotion; submitting is free, so nothing is owed either way."""
    with tx(ctx.engine) as conn:
        sub = lock_submission(conn, sub_id)
        if sub.hotkey != hotkey:
            raise ServiceError("forbidden", "only the submitting hotkey can withdraw", 403)
        _set_state(
            conn,
            sub_id,
            sub.state,
            "withdraw",
            reserved_centi=0,
            outcome_code="withdrawn",
            outcome_summary=f"Withdrawn by the miner: {reason[:200]}",
        )
        audit.append(conn, hotkey, "withdrawn", "submission", sub_id, {}, public=True)
        return {"state": "withdrawn"}
