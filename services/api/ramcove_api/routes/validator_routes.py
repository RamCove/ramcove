"""Validator calls that stand in for the chain in simulation mode. Local door only (see channel.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..services import validator_chain
from ..services.context import AppContext
from .deps import get_ctx, require_session

router = APIRouter(prefix="/v1/validator", tags=["validator"])


class WeightsIn(BaseModel):
    uids: list[int] = Field(min_length=1, max_length=256)
    weights: list[int] = Field(min_length=1, max_length=256)
    version_key: int
    document_hash: str = Field(min_length=64, max_length=64)


@router.get("/chain", tags=["demo"])
def chain(ctx: AppContext = Depends(get_ctx)) -> dict:
    """SIMULATION: the dev chain's finalized head, genesis hash and UID map, as a validator reads them."""
    return validator_chain.chain_view(ctx)


@router.post("/weights", tags=["demo"])
def weights(
    body: WeightsIn, ctx: AppContext = Depends(get_ctx), sess: dict = Depends(require_session)
) -> dict:
    """SIMULATION: submits set_weights on the dev chain, signed in as the validator's hotkey."""
    return validator_chain.submit_weights(
        ctx, sess["hotkey"], body.uids, body.weights, body.version_key, body.document_hash
    )
