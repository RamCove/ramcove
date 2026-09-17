"""Worker registration state: 'online' (recent heartbeat) is distinct from 'safe and ready to evaluate'."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update

from ..store import audit
from ..store.db import now, tx
from ..store.schema import workers
from .context import AppContext, ServiceError


def heartbeat(ctx: AppContext, worker_id: str, readiness: dict[str, Any]) -> dict:
    with tx(ctx.engine) as conn:
        w = conn.execute(select(workers).where(workers.c.id == worker_id).with_for_update()).first()
        if w is None or not w.enabled:
            raise ServiceError("unknown_worker", "worker is not registered or disabled", 403)
        ready = bool(readiness.get("safe_and_ready"))
        if readiness.get("simulated") and not ctx.settings.simulated_chain:
            ready = False  # a simulated provider can never serve a real network
        merged = {**{k: v for k, v in w.readiness.items() if k == "calibration"}, **readiness}
        conn.execute(
            update(workers)
            .where(workers.c.id == worker_id)
            .values(last_heartbeat=now(), readiness=merged, ready=ready)
        )
        if ready != w.ready:
            audit.append(conn, worker_id, "worker_readiness_changed", "worker", worker_id, {"ready": ready})
        return {"ready": ready}
