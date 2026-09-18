"""Worker routes. Signed with the worker's registered key; no database access is exposed."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from ..services import queue
from ..services import workers as workers_svc
from ..services.context import AppContext, ServiceError
from ..store.db import tx
from ..store.schema import artifacts
from .deps import get_ctx, worker_identity

router = APIRouter(prefix="/v1/worker", tags=["worker"])


class HeartbeatIn(BaseModel):
    readiness: dict


class CompleteIn(BaseModel):
    result: dict


@router.post("/heartbeat")
def heartbeat(
    body: HeartbeatIn, ctx: AppContext = Depends(get_ctx), worker: str = Depends(worker_identity)
) -> dict:
    return workers_svc.heartbeat(ctx, worker, body.readiness)


@router.post("/lease")
def lease(ctx: AppContext = Depends(get_ctx), worker: str = Depends(worker_identity)) -> dict:
    payload = queue.lease_next(ctx, worker)
    return {"job": payload}


@router.get("/artifacts/{sha256}")
def artifact(
    sha256: str, ctx: AppContext = Depends(get_ctx), worker: str = Depends(worker_identity)
) -> Response:
    from sqlalchemy import select

    with tx(ctx.engine) as conn:
        row = conn.execute(select(artifacts).where(artifacts.c.sha256 == sha256)).first()
    if row is None:
        raise ServiceError("not_found", "artifact not found", 404)
    return Response(ctx.artifacts.get(row.storage_key), media_type="application/gzip")


@router.post("/jobs/{job_id}/complete")
def complete(
    job_id: str, body: CompleteIn, ctx: AppContext = Depends(get_ctx), worker: str = Depends(worker_identity)
) -> dict:
    return queue.complete(ctx, worker, job_id, body.result)
