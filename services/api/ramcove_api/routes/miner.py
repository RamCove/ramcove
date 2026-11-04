"""Miner routes: free preflight, free admission to the queue, withdrawal, appeals."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile
from pydantic import BaseModel, Field

from ..services import intake, public, review
from ..services.context import AppContext, ServiceError
from .deps import get_ctx, idempotent, require_session

router = APIRouter(prefix="/v1/miner", tags=["miner"])
MAX_UPLOAD = 20 * 1024 * 1024


class WithdrawIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class AppealIn(BaseModel):
    grounds: str = Field(min_length=20, max_length=2000)


@router.post("/preflight")
async def preflight(
    file: UploadFile = File(...),
    signature: str = Form(...),
    ctx: AppContext = Depends(get_ctx),
    sess: dict = Depends(require_session),
) -> dict:
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise ServiceError("archive_too_large", f"artifact must be at most {MAX_UPLOAD} bytes", 413)
    return intake.preflight(ctx, sess["hotkey"], data, signature)


@router.get("/submissions")
def my_submissions(ctx: AppContext = Depends(get_ctx), sess: dict = Depends(require_session)) -> dict:
    return public.my_submissions(ctx, sess["hotkey"])


@router.post("/submissions/{submission_id}/admit")
def admit(
    submission_id: str,
    ctx: AppContext = Depends(get_ctx),
    sess: dict = Depends(require_session),
    idempotency_key: str | None = Header(None),
) -> dict:
    """Join the queue, free of charge: admitted when evaluation capacity is free, otherwise placed on the
    free waiting list. Needs a hotkey registered on the subnet."""
    return idempotent(
        ctx,
        sess["hotkey"],
        "admit",
        idempotency_key,
        lambda: intake.admit(ctx, submission_id, sess["hotkey"]),
    )


@router.post("/submissions/{submission_id}/withdraw")
def withdraw(
    submission_id: str,
    body: WithdrawIn,
    ctx: AppContext = Depends(get_ctx),
    sess: dict = Depends(require_session),
) -> dict:
    return intake.withdraw(ctx, submission_id, sess["hotkey"], body.reason)


@router.post("/submissions/{submission_id}/appeal")
def appeal(
    submission_id: str,
    body: AppealIn,
    ctx: AppContext = Depends(get_ctx),
    sess: dict = Depends(require_session),
) -> dict:
    return review.open_appeal(ctx, submission_id, sess["hotkey"], body.grounds)
