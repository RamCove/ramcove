"""Shared dependencies: context, session, roles, idempotency and worker request signatures."""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import Depends, Header, Request
from room_protocol.canonical import signing_payload
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ..services.auth import session_for
from ..services.context import AppContext, ServiceError
from ..signing import verify_sr25519
from ..store.db import now, tx
from ..store.schema import idempotency, workers

SESSION_COOKIE = "room_session"
WORKER_CLOCK_SKEW_S = 120


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def session(request: Request, ctx: AppContext = Depends(get_ctx)) -> dict | None:
    return session_for(ctx, request.cookies.get(SESSION_COOKIE))


def require_session(sess: dict | None = Depends(session)) -> dict:
    if sess is None:
        raise ServiceError("unauthenticated", "sign in with your hotkey first", 401)
    return sess


def require_role(*roles: str):
    def dep(sess: dict = Depends(require_session)) -> dict:
        if not set(roles) & set(sess["roles"]):
            raise ServiceError("forbidden", f"this action needs the {' or '.join(roles)} role", 403)
        return sess

    return dep


def idempotent(ctx: AppContext, actor: str, route: str, key: str | None, produce) -> Any:
    """Store-and-replay: a refresh or double click cannot create a second payment or submission."""
    if not key:
        return produce()
    with tx(ctx.engine) as conn:
        prior = conn.execute(
            select(idempotency).where(
                idempotency.c.key == key, idempotency.c.actor == actor, idempotency.c.route == route
            )
        ).first()
        if prior:
            return {**prior.response, "idempotent_replay": True}
    result = produce()
    with tx(ctx.engine) as conn:
        conn.execute(
            insert(idempotency)
            .values(key=key, actor=actor, route=route, response=result)
            .on_conflict_do_nothing()
        )
    return result


async def worker_identity(
    request: Request,
    ctx: AppContext = Depends(get_ctx),
    x_room_worker: str | None = Header(None),
    x_room_timestamp: str | None = Header(None),
    x_room_signature: str | None = Header(None),
) -> str:
    """Workers sign every request with their registered key; the controller database is never exposed to them."""
    if not (x_room_worker and x_room_timestamp and x_room_signature):
        raise ServiceError("unauthenticated", "worker signature headers are required", 401)
    try:
        ts = int(x_room_timestamp)
    except ValueError as e:
        raise ServiceError("bad_timestamp", "invalid timestamp", 422) from e
    if abs(int(now().timestamp()) - ts) > WORKER_CLOCK_SKEW_S:
        raise ServiceError("stale_request", "worker request timestamp is outside the accepted window", 401)
    body = await request.body()
    with tx(ctx.engine) as conn:
        w = conn.execute(select(workers).where(workers.c.id == x_room_worker)).first()
    if w is None or not w.enabled:
        raise ServiceError("unknown_worker", "worker is not registered or is disabled", 403)
    payload = signing_payload(
        "worker_request",
        ctx.settings.network,
        {
            "worker": x_room_worker,
            "method": request.method,
            "path": request.url.path,
            "timestamp": ts,
            "body_sha256": hashlib.sha256(body).hexdigest(),
        },
    )
    try:
        sig = bytes.fromhex(x_room_signature.removeprefix("0x"))
    except ValueError as e:
        raise ServiceError("bad_signature", "signature must be hex", 422) from e
    if not verify_sr25519(w.public_key, payload, sig):
        raise ServiceError("bad_signature", "worker signature does not verify", 401)
    return x_room_worker
