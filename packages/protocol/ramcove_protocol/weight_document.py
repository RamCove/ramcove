"""Signed weight results: what the owner publishes and what every validator submits (Section 7.5).

The owner's evaluation produces a weight plan (``weights.build_weight_plan``). Every tempo the owner signs a
*weight document* built from it: the share of the miner allocation each hotkey receives, valid for a
window of blocks. Only validators can fetch the document: each read is signed with the validator's hotkey
(``fetch_payload``) and the owner serves it only to a hotkey with a validator permit. The validator checks
the owner's signature against a pinned signer, maps the hotkeys to UIDs from its own chain reads, and
submits those weights. Validators that set weights this way run no evaluation of their own: they rely on
the owner's scores.

Shares are keyed by hotkey, never by UID, because a UID number can pass to another hotkey. A hotkey that
is not registered when a validator reads the chain has its share moved to the burn hotkey.

Pure and deterministic: no network, no database, no signing library. Signing and verification live with
the service and the validator, which hold the keys.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .canonical import record_hash, signing_payload
from .weights import U16_MAX, KingSlot

SCHEMA = "ramcove.weight_document/1"
RECORD_TYPE = "weight_document"
TEMPO_BLOCKS = 360  # Bittensor's default tempo
VALID_TEMPOS = 2  # a document is valid for two tempos and re-issued when less than one remains
LATEST_PATH = "/v1/weights/latest"
FETCH_RECORD_TYPE = "weight_fetch"
FETCH_CLOCK_SKEW_S = 120  # a signed read is accepted for two minutes either side of the owner's clock


class WeightDocumentError(ValueError):
    pass


def build_weight_document(
    kings: Sequence[KingSlot],
    *,
    netuid: int,
    network: str,
    genesis_hash: str,
    burn_hotkey: str,
    issued_block: int,
    plan_id: str,
    rule_hash: str,
    champion_version: int,
    weights_version_key: int,
) -> dict[str, Any]:
    """The document the owner signs: each paid king's share, and the rest to the burn hotkey."""
    shares: dict[str, int] = {}
    for k in kings:
        if k.paid and k.hotkey is not None:
            shares[k.hotkey] = shares.get(k.hotkey, 0) + k.share_bp
    burn_bp = 10_000 - sum(shares.values())
    if burn_bp < 0:
        raise WeightDocumentError("king shares exceed the whole miner allocation")
    rows = [{"hotkey": hk, "share_bp": bp, "role": "king"} for hk, bp in sorted(shares.items())]
    if burn_bp:
        rows.append({"hotkey": burn_hotkey, "share_bp": burn_bp, "role": "burn"})
    return {
        "schema": SCHEMA,
        "network": network,
        "genesis_hash": genesis_hash,
        "netuid": netuid,
        "issued_block": issued_block,
        "valid_until_block": issued_block + VALID_TEMPOS * TEMPO_BLOCKS,
        "plan_id": plan_id,
        "rule_hash": rule_hash,
        "champion_version": champion_version,
        "weights_version_key": weights_version_key,
        "burn_hotkey": burn_hotkey,
        "shares": rows,
        "kings": [
            {
                "profile_id": k.profile_id,
                "slot": k.slot,
                "hotkey": k.hotkey,
                "champion_version": k.champion_version,
                "share_bp": k.share_bp,
                "paid": k.paid,
                "reason": k.reason,
            }
            for k in kings
        ],
    }


def fetch_payload(network: str, hotkey: str, timestamp: int, path: str = LATEST_PATH) -> bytes:
    """The bytes a validator signs with its hotkey to read the owner's weight result. Domain-separated by
    record type and network, and bound to the path and a timestamp so a signed read cannot be reused later."""
    return signing_payload(
        FETCH_RECORD_TYPE,
        network,
        {"hotkey": hotkey, "method": "GET", "path": path, "timestamp": int(timestamp)},
    )


def document_hash(doc: Mapping[str, Any]) -> str:
    return record_hash(dict(doc))


def signed_bytes(doc: Mapping[str, Any]) -> bytes:
    """The exact bytes the owner signs: domain-separated by record type and network."""
    return signing_payload(RECORD_TYPE, str(doc["network"]), dict(doc))


def needs_reissue(doc: Mapping[str, Any] | None, plan_id: str, head_block: int) -> bool:
    """A new document is due when there is none, when the plan changed, or when less than a tempo is left."""
    if doc is None or doc.get("plan_id") != plan_id:
        return True
    return head_block > int(doc["valid_until_block"]) - TEMPO_BLOCKS


def check_document(
    doc: Mapping[str, Any], *, network: str, genesis_hash: str, netuid: int, finalized_block: int
) -> list[str]:
    """Everything a validator checks besides the signature. An empty list means the document is usable."""
    problems: list[str] = []
    if doc.get("schema") != SCHEMA:
        return [f"unknown schema {doc.get('schema')!r}"]
    if doc.get("network") != network:
        problems.append(f"document is for network {doc.get('network')!r}, not {network!r}")
    if str(doc.get("genesis_hash", "")).lower() != genesis_hash.lower():
        problems.append("document genesis hash does not match the chain")
    if doc.get("netuid") != netuid:
        problems.append(f"document is for netuid {doc.get('netuid')!r}, not {netuid}")
    issued, until = int(doc.get("issued_block", -1)), int(doc.get("valid_until_block", -1))
    if not issued <= finalized_block <= until:
        problems.append(
            f"document is valid for blocks {issued}..{until}; the finalized head is {finalized_block}"
        )
    shares = doc.get("shares") or []
    if sum(int(r.get("share_bp", 0)) for r in shares) != 10_000:
        problems.append("shares do not add up to the whole miner allocation")
    if any(int(r.get("share_bp", 0)) <= 0 for r in shares):
        problems.append("every share must be positive")
    if len({r.get("hotkey") for r in shares}) != len(shares):
        problems.append("a hotkey appears twice")
    return problems


def chain_weights(
    doc: Mapping[str, Any], hotkey_to_uid: Mapping[str, int]
) -> tuple[list[int], list[int], list[str]]:
    """UIDs and u16 weights to submit, from the validator's own UID map.

    The share of a hotkey that is not registered goes to the burn hotkey, which must be registered."""
    burn = str(doc["burn_hotkey"])
    if burn not in hotkey_to_uid:
        raise WeightDocumentError("the burn hotkey is not registered on this subnet; refusing to submit")
    notes: list[str] = []
    per_uid: dict[int, int] = {}
    for r in doc["shares"]:
        hk, bp = str(r["hotkey"]), int(r["share_bp"])
        uid = hotkey_to_uid.get(hk)
        if uid is None:
            notes.append(f"{hk} is not registered; its share goes to the burn hotkey")
            uid = hotkey_to_uid[burn]
        per_uid[uid] = per_uid.get(uid, 0) + bp
    uids = sorted(per_uid)
    return uids, [per_uid[u] * U16_MAX // 10_000 for u in uids], notes
