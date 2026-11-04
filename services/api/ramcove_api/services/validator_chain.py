"""Simulation mode: the chain reads and weight submission a validator would otherwise do on the network.

In network mode ``ramcove-validator`` reads the real chain and submits weights there itself. In simulation
the chain lives inside this service, so these two calls stand in for it: a read of the UID map and finality,
and a ``set_weights`` signed in as the validator's hotkey.
"""

from __future__ import annotations

from ramcove_chain.devchain import weights_call

from ..store import audit
from ..store.db import tx
from .context import AppContext, ServiceError


def _require_simulated(ctx: AppContext) -> None:
    if not ctx.settings.simulated_chain:
        raise ServiceError(
            "read_the_chain", "in network mode a validator reads and writes the chain directly", 409
        )


def chain_view(ctx: AppContext) -> dict:
    _require_simulated(ctx)
    with tx(ctx.engine) as conn:
        chain = ctx.chain(conn)
        block, uids = chain.hotkey_uid_map(ctx.settings.netuid)
        return {
            "network": ctx.settings.network,
            "genesis_hash": chain.genesis_hash(),
            "netuid": ctx.settings.netuid,
            "finalized_block": block,
            "hotkey_to_uid": uids,
            "owner_hotkey": ctx.owner_hotkey,
            "simulated": True,
        }


def submit_weights(
    ctx: AppContext, hotkey: str, uids: list[int], weights: list[int], version_key: int, document_hash: str
) -> dict:
    _require_simulated(ctx)
    with tx(ctx.engine) as conn:
        chain = ctx.chain(conn)
        number = chain.produce_block(
            [(hotkey, weights_call(ctx.settings.netuid, uids, weights, version_key))]
        )
        ext = chain.extrinsics(number)[0]
        error = next(
            (e.attributes.get("dispatch_error") for e in ext.events if e.name == "ExtrinsicFailed"), None
        )
        if error is None:
            audit.append(
                conn,
                hotkey,
                "validator_weights_set",
                "weight_document",
                document_hash,
                # public, so it records that the validator set weights, not the weights themselves: the
                # weights are served only to validators
                {"block_number": number, "weight_count": len(uids), "simulated": True},
                public=True,
            )
        return {
            "ok": error is None,
            "error": error,
            "block_number": number,
            "extrinsic_index": ext.index,
            "simulated": True,
        }
