"""Sessions from hotkey signatures. Demo sign-in exists only in demo mode and is labelled everywhere."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from room_protocol.auth import Challenge, ChallengeError, verify_challenge
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from substrateinterface import Keypair

from ..signing import verify_sr25519
from ..store import audit
from ..store.db import now, tx
from ..store.schema import auth_challenges, identities, role_grants, sessions
from .context import AppContext, ServiceError

CHALLENGE_TTL = timedelta(minutes=10)
SESSION_TTL = timedelta(hours=12)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_challenge(ctx: AppContext, hotkey: str) -> dict:
    if not hotkey or len(hotkey) < 46:
        raise ServiceError("bad_hotkey", "provide a valid ss58 hotkey address", 422)
    with tx(ctx.engine) as conn:
        nonce = secrets.token_hex(16)
        ch = Challenge(
            domain=ctx.settings.public_origin,
            network=ctx.settings.network,
            genesis_hash=ctx.network_identity.genesis_hash,
            hotkey=hotkey,
            nonce=nonce,
            issued_at=now(),
            expires_at=now() + CHALLENGE_TTL,
        )
        conn.execute(
            auth_challenges.insert().values(
                nonce=nonce,
                hotkey=hotkey,
                domain=ch.domain,
                network=ch.network,
                genesis_hash=ch.genesis_hash,
                issued_at=ch.issued_at,
                expires_at=ch.expires_at,
            )
        )
        return {"nonce": nonce, "message": ch.message().decode(), "expires_at": ch.expires_at}


def verify_and_open_session(ctx: AppContext, nonce: str, signature_hex: str) -> tuple[str, dict]:
    with tx(ctx.engine) as conn:
        row = conn.execute(
            select(auth_challenges).where(auth_challenges.c.nonce == nonce).with_for_update()
        ).first()
        if row is None:
            raise ServiceError("unknown_challenge", "challenge not found", 404)
        if row.used_at is not None:
            raise ServiceError("challenge_used", "this challenge was already used", 409)
        ch = Challenge(
            row.domain, row.network, row.genesis_hash, row.hotkey, row.nonce, row.issued_at, row.expires_at
        )
        try:
            sig = bytes.fromhex(signature_hex.removeprefix("0x"))
        except ValueError as e:
            raise ServiceError("bad_signature", "signature must be hex", 422) from e
        try:
            verify_challenge(
                ch,
                sig,
                verify_sr25519,
                now(),
                ctx.settings.public_origin,
                ctx.settings.network,
                ctx.network_identity.genesis_hash,
            )
        except ChallengeError as e:
            raise ServiceError("bad_signature", str(e), 401) from e
        conn.execute(update(auth_challenges).where(auth_challenges.c.nonce == nonce).values(used_at=now()))
        return _open_session(conn, ctx, row.hotkey, demo=False)


def _open_session(conn, ctx: AppContext, hotkey: str, demo: bool) -> tuple[str, dict]:
    conn.execute(
        insert(identities).values(hotkey=hotkey, display_name=None, demo=demo).on_conflict_do_nothing()
    )
    token = secrets.token_urlsafe(32)
    conn.execute(
        sessions.insert().values(
            token_hash=token_hash(token), hotkey=hotkey, demo=demo, expires_at=now() + SESSION_TTL
        )
    )
    audit.append(conn, hotkey, "signed_in", "identity", hotkey, {"demo": demo})
    return token, {"hotkey": hotkey, "demo": demo, "roles": sorted(_roles(conn, hotkey))}


def demo_sign_in(ctx: AppContext, identity_key: str) -> tuple[str, dict]:
    if not ctx.settings.demo_features:
        raise ServiceError("disabled", "demo sign-in is disabled outside demo mode", 403)
    from .seed import identity as demo_identity

    d, kp = demo_identity(identity_key)
    with tx(ctx.engine) as conn:
        return _open_session(conn, ctx, kp.ss58_address, demo=True)


def demo_keypair(ctx: AppContext, hotkey: str) -> Keypair:
    """Server-side signing on behalf of a demo identity (demo mode only, for browser flows without a wallet)."""
    if not ctx.settings.demo_features:
        raise ServiceError("disabled", "demo signing is disabled outside demo mode", 403)
    from .seed import DEMO_IDENTITIES

    for d in DEMO_IDENTITIES:
        kp = Keypair.create_from_uri(d.uri)
        if kp.ss58_address == hotkey:
            return kp
    raise ServiceError("not_demo_identity", "this hotkey is not a demo identity", 403)


def _roles(conn, hotkey: str) -> set[str]:
    return {r.role for r in conn.execute(select(role_grants).where(role_grants.c.hotkey == hotkey)).all()}


def session_for(ctx: AppContext, token: str | None) -> dict | None:
    if not token:
        return None
    with tx(ctx.engine) as conn:
        row = conn.execute(select(sessions).where(sessions.c.token_hash == token_hash(token))).first()
        if row is None or row.revoked_at is not None or row.expires_at < now():
            return None
        return {"hotkey": row.hotkey, "demo": row.demo, "roles": sorted(_roles(conn, row.hotkey))}


def sign_out(ctx: AppContext, token: str | None) -> None:
    if not token:
        return
    with tx(ctx.engine) as conn:
        conn.execute(
            update(sessions).where(sessions.c.token_hash == token_hash(token)).values(revoked_at=now())
        )
