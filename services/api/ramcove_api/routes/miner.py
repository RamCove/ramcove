"""Miner routes: preflight, reservation and quote, payment, recovery, withdrawal, appeals."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile
from pydantic import BaseModel, Field

from ..services import intake, public, review
from ..services.context import AppContext, ServiceError
from ..services.payments import recover_payment
from .deps import get_ctx, idempotent, require_session

router = APIRouter(prefix="/v1/miner", tags=["miner"])
MAX_UPLOAD = 20 * 1024 * 1024


class ReserveIn(BaseModel):
    payer: str | None = Field(None, description="Account authorized to pay; defaults to the signed-in hotkey")


class RecoverIn(BaseModel):
    block_number: int
    extrinsic_index: int


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


@router.post("/submissions/{submission_id}/reserve")
def reserve(
    submission_id: str,
    body: ReserveIn,
    ctx: AppContext = Depends(get_ctx),
    sess: dict = Depends(require_session),
    idempotency_key: str | None = Header(None),
) -> dict:
    return idempotent(
        ctx,
        sess["hotkey"],
        "reserve",
        idempotency_key,
        lambda: intake.reserve(ctx, submission_id, sess["hotkey"], body.payer or sess["hotkey"]),
    )


@router.post("/quotes/{quote_id}/pay-simulated", tags=["demo"])
def pay_simulated(
    quote_id: str,
    ctx: AppContext = Depends(get_ctx),
    sess: dict = Depends(require_session),
    idempotency_key: str | None = Header(None),
) -> dict:
    """SIMULATION: signs and submits the payment on the dev chain for a demo identity."""
    return idempotent(
        ctx, sess["hotkey"], "pay", idempotency_key, lambda: intake.demo_pay(ctx, quote_id, sess["hotkey"])
    )


@router.post("/payments/recover")
def recover(
    body: RecoverIn, ctx: AppContext = Depends(get_ctx), sess: dict = Depends(require_session)
) -> dict:
    return recover_payment(ctx, sess["hotkey"], body.block_number, body.extrinsic_index)


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
