"""Free preflight, waiting list, capacity reservation and signed quotes (Sections 6.2-6.3; review R3)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from room_chain.devchain import payment_call
from room_protocol.canonical import record_hash, signing_payload
from room_protocol.fees import StalePriceError, compute_fee
from room_protocol.money import format_tao
from room_protocol.preflight import run_preflight
from room_protocol.reservation import can_issue_quote
from room_protocol.state import S, next_state, withdrawal_fee_outcome
from sqlalchemy import Connection, select, update
from sqlalchemy.exc import IntegrityError

from ..signing import verify_sr25519
from ..store import audit
from ..store.db import advisory_lock, new_id, now, support_ref, tx
from ..store.schema import artifacts, quotes, rate_counters, submissions
from .context import AppContext, ServiceError, load_trusted_fixtures

PREFLIGHT_PER_DAY = 10


def artifact_signing_body(sha256: str, profile_id: str, version: str, hotkey: str) -> dict[str, Any]:
    return {"artifact_sha256": sha256, "profile_id": profile_id, "profile_version": version, "hotkey": hotkey}


def _rate_limit(conn: Connection, bucket: str, limit: int, window: timedelta) -> None:
    t = now()
    row = conn.execute(
        select(rate_counters).where(rate_counters.c.bucket == bucket).with_for_update()
    ).first()
    if row is None:
        conn.execute(rate_counters.insert().values(bucket=bucket, count=1, window_start=t))
        return
    if t - row.window_start > window:
        conn.execute(
            update(rate_counters).where(rate_counters.c.bucket == bucket).values(count=1, window_start=t)
        )
        return
    if row.count >= limit:
        raise ServiceError(
            "rate_limited", f"preflight is limited to {limit} checks per day for this hotkey", 429
        )
    conn.execute(update(rate_counters).where(rate_counters.c.bucket == bucket).values(count=row.count + 1))


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
        _rate_limit(conn, f"preflight:{hotkey}", PREFLIGHT_PER_DAY, timedelta(days=1))
        known = set()
        for r in conn.execute(select(artifacts.c.sha256, artifacts.c.normalized_patch_sha256)):
            known.update({r.sha256, r.normalized_patch_sha256})
        from room_protocol.canonical import sha256_hex

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


def reserve(ctx: AppContext, sub_id: str, hotkey: str, payer: str) -> dict[str, Any]:
    """Reserve capacity and issue a signed quote, or place the submission on the free waiting list."""
    with tx(ctx.engine) as conn:
        sub = lock_submission(conn, sub_id)
        if sub.hotkey != hotkey:
            raise ServiceError("forbidden", "only the submitting hotkey can reserve", 403)
        if sub.state not in (S.PREFLIGHT_PASSED, S.INVITED, S.WAITLISTED):
            raise ServiceError("bad_state", f"cannot reserve from state {sub.state}", 409)
        if sub.state == S.WAITLISTED:
            return {
                "status": "waitlisted",
                "message": "you are on the free waiting list; you will be invited",
            }
        profile = ctx.profile(conn, sub.profile_id)
        if profile.rule_hash() != sub.rule_hash:
            raise ServiceError("profile_changed", "the profile version changed; run preflight again", 409)
        advisory_lock(conn, f"capacity:{profile.profile_id}")
        art = conn.execute(select(artifacts).where(artifacts.c.sha256 == sub.artifact_sha256)).first()
        plan = ctx.capacity_plan(conn, profile, trusted_fixture=bool(art.trusted_fixture))
        paused = bool(ctx.setting(conn, "intake_paused", {"paused": False}).get("paused"))
        check = can_issue_quote(ctx.committed_centi(conn, profile.profile_id), profile.envelope, plan, paused)
        if not check.allowed:
            if sub.state == S.PREFLIGHT_PASSED:
                _set_state(conn, sub_id, sub.state, "waitlist", waitlisted_at=now())
            elif sub.state == S.INVITED:
                _set_state(
                    conn, sub_id, sub.state, "invitation_missed", waitlisted_at=now(), invited_until=None
                )
            audit.append(conn, hotkey, "waitlisted", "submission", sub_id, {"reason": check.reason})
            return {
                "status": "waitlisted",
                "message": check.reason,
                "capacity": check.__dict__,
                "no_fee": True,
            }
        price = ctx.latest_price(conn)
        if price is None:
            raise ServiceError("price_unavailable", "no price observation; new quotes are refused", 503)
        try:
            fee = compute_fee(profile.fees, price, now())
        except StalePriceError as e:
            raise ServiceError("price_stale", str(e), 503) from e
        chain = ctx.chain(conn)
        head = chain.finalized_head()
        quote_id = new_id("q")
        body = {
            "schema": "room.quote/1",
            "quote_id": quote_id,
            "network": ctx.settings.network,
            "genesis_hash": ctx.network_identity.genesis_hash,
            "hotkey": hotkey,
            "payer": payer,
            "recipient": ctx.evaluation_wallet,
            "artifact_sha256": sub.artifact_sha256,
            "profile_id": profile.profile_id,
            "profile_version": profile.version,
            "rule_hash": sub.rule_hash,
            "amount_rao": fee.fee_rao,
            "issued_block": head.number,
            "expires_block": head.number + profile.deadlines.quote_ttl_blocks,
            "remark": "room:quote:" + quote_id,
            "price_usd_micros": price.usd_micros_per_tao,
            "price_observed_at": price.observed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "price_simulated": price.simulated,
        }
        signature = ctx.signer.sign("quote", body)
        conn.execute(
            quotes.insert().values(
                id=quote_id,
                submission_id=sub_id,
                network=ctx.settings.network,
                hotkey=hotkey,
                payer=payer,
                recipient=ctx.evaluation_wallet,
                artifact_sha256=sub.artifact_sha256,
                rule_hash=sub.rule_hash,
                amount_rao=fee.fee_rao,
                issued_block=head.number,
                expires_block=body["expires_block"],
                price_usd_micros=price.usd_micros_per_tao,
                price_observed_at=price.observed_at,
                price_simulated=price.simulated,
                target_usd_cents=fee.target_usd_cents,
                fee_usd_cents=fee.fee_usd_cents_at_price,
                service_cost_usd_cents=fee.service_cost_usd_cents,
                reserved_centi=check.requested_centi,
                body=body,
                signature=signature,
            )
        )
        _set_state(conn, sub_id, sub.state, "quote", reserved_centi=check.requested_centi, invited_until=None)
        audit.append(
            conn,
            hotkey,
            "quote_issued",
            "submission",
            sub_id,
            {"quote_id": quote_id, "amount_rao": fee.fee_rao, "quote_hash": record_hash(body)},
        )
        return {
            "status": "quoted",
            "quote": body,
            "signature": signature,
            "signer": ctx.signer.address,
            "display": {
                "amount_tao": format_tao(fee.fee_rao),
                "target_usd_cents": fee.target_usd_cents,
                "fee_usd_cents_at_price": fee.fee_usd_cents_at_price,
                "service_cost_usd_cents": fee.service_cost_usd_cents,
                "subsidy_usd_cents": fee.subsidy_usd_cents,
                "estimated_network_fee_rao": 166_251,
            },
        }


def demo_pay(
    ctx: AppContext, quote_id: str, hotkey: str, plain_batch: bool = False, amount_override: int | None = None
) -> dict[str, Any]:
    """SIMULATION: submit the payment extrinsic to the dev chain on behalf of a demo payer account."""
    if not ctx.settings.demo_features:
        raise ServiceError("disabled", "demo payments are only available in demo mode", 403)
    with tx(ctx.engine) as conn:
        q = conn.execute(select(quotes).where(quotes.c.id == quote_id).with_for_update()).first()
        if q is None or q.hotkey != hotkey:
            raise ServiceError("not_found", "quote not found", 404)
        if q.status != "open":
            raise ServiceError(
                "quote_not_open", f"quote is {q.status}; recover the existing payment instead", 409
            )
        chain = ctx.chain(conn)
        if chain.store.balance(q.payer) < q.amount_rao + 10**9:
            chain.store.set_balance(q.payer, 5 * 10**9)  # demo faucet, simulated funds only
        block = chain.produce_block(
            [
                (
                    q.payer,
                    payment_call(q.recipient, amount_override or q.amount_rao, q.id, plain_batch=plain_batch),
                )
            ]
        )
        audit.append(
            conn, hotkey, "demo_payment_submitted", "quote", q.id, {"block": block, "simulated": True}
        )
        return {
            "simulated": True,
            "block_number": block,
            "extrinsic_index": 0,
            "message": "Simulated payment included; it counts only after the dev chain finalizes it.",
        }


def withdraw(ctx: AppContext, sub_id: str, hotkey: str, reason: str) -> dict[str, Any]:
    from .accounting import issue_credit

    with tx(ctx.engine) as conn:
        sub = lock_submission(conn, sub_id)
        if sub.hotkey != hotkey:
            raise ServiceError("forbidden", "only the submitting hotkey can withdraw", 403)
        outcome = withdrawal_fee_outcome(sub.state)
        _set_state(
            conn,
            sub_id,
            sub.state,
            "withdraw",
            fee_outcome=outcome,
            reserved_centi=0,
            outcome_code="withdrawn",
            outcome_summary=f"Withdrawn by the miner: {reason[:200]}",
        )
        conn.execute(
            update(quotes)
            .where(quotes.c.submission_id == sub_id, quotes.c.status == "open")
            .values(status="withdrawn")
        )
        if outcome == "credit":
            q = conn.execute(
                select(quotes).where(quotes.c.submission_id == sub_id, quotes.c.status == "paid")
            ).first()
            if q:
                issue_credit(
                    conn,
                    ctx,
                    hotkey,
                    q.amount_rao,
                    "withdrawn before GPU work started",
                    sub_id,
                    f"withdraw:{sub_id}",
                )
        audit.append(conn, hotkey, "withdrawn", "submission", sub_id, {"fee_outcome": outcome}, public=True)
        return {"state": "withdrawn", "fee_outcome": outcome}
