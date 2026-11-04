"""Who may read the owner's weight result: validators, and nobody else.

Every read of ``/v1/weights/latest`` is signed with the reader's hotkey (``weight_document.fetch_payload``)
and carries a timestamp within ``FETCH_CLOCK_SKEW_S`` of this service's clock. The hotkey must hold a
validator permit:

- in simulation the dev chain has no stake, so a validator is a hotkey the owner lists in the validators
  table that is registered on the dev chain;
- on a real network it is a hotkey with Bittensor's validator permit on the subnet
  (``SubstrateReader.validator_permit_hotkeys``). This service reads the network from launch step 3; until
  then the check refuses every read, so the result is never served to an unchecked hotkey.
"""

from __future__ import annotations

from ramcove_protocol.weight_document import FETCH_CLOCK_SKEW_S, fetch_payload
from sqlalchemy import select

from ..signing import verify_sr25519
from ..store.db import now, tx
from ..store.schema import validators
from .context import AppContext, ServiceError


def require_validator(
    ctx: AppContext, hotkey: str | None, timestamp: str | None, signature: str | None, path: str
) -> str:
    if not (hotkey and timestamp and signature):
        raise ServiceError(
            "validator_signature_required",
            "the weight result is served only to validators: sign the request with your validator hotkey",
            401,
        )
    try:
        ts = int(timestamp)
    except ValueError as e:
        raise ServiceError("bad_timestamp", "invalid timestamp", 422) from e
    if abs(int(now().timestamp()) - ts) > FETCH_CLOCK_SKEW_S:
        raise ServiceError("stale_request", "the request timestamp is outside the accepted window", 401)
    try:
        sig = bytes.fromhex(signature.removeprefix("0x"))
    except ValueError as e:
        raise ServiceError("bad_signature", "signature must be hex", 422) from e
    if not verify_sr25519(hotkey, fetch_payload(ctx.settings.network, hotkey, ts, path), sig):
        raise ServiceError("bad_signature", "the signature does not verify for this hotkey", 401)
    if not ctx.settings.simulated_chain:
        raise ServiceError(
            "permit_check_unavailable",
            "this service reads validator permits from the network from launch step 3",
            503,
        )
    with tx(ctx.engine) as conn:
        listed = conn.execute(select(validators.c.hotkey).where(validators.c.hotkey == hotkey)).first()
        _, uids = ctx.chain(conn).hotkey_uid_map(ctx.settings.netuid)
    if listed is None or hotkey not in uids:
        raise ServiceError(
            "not_a_validator", "this hotkey does not hold a validator permit on this subnet", 403
        )
    return hotkey
