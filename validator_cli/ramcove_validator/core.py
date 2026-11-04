"""One validator cycle: fetch the owner's signed weight result, check it, map it to UIDs, submit it.

A validator running this program does not evaluate miners. It relies on the scores the owner-operated
validator publishes, and it checks only what it can check itself: that the result is signed by the pinned
owner key, is for this chain and subnet, is still valid at the finalized head, and burns to the subnet
owner. Anything missing or wrong stops the submission; it never invents weights of its own.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ramcove_protocol.weight_document import (
    TEMPO_BLOCKS,
    WeightDocumentError,
    chain_weights,
    check_document,
    document_hash,
    signed_bytes,
)

# The owner's weight-signing key per network. A validator trusts only this pin, never a signer named by
# the server it fetches from. The development chain's key is the published demo service key.
PINNED_SIGNERS: dict[str, str | None] = {
    "ramcove-devchain": "5DHka7cdFE3pGpuAXZ7ZAVukk2hUvpzu8FYKpH7gq32LBtsG",
    "test": None,  # pinned in the release for testnet
    "finney": None,  # pinned in the release for mainnet
}
RESUBMIT_BLOCKS = TEMPO_BLOCKS  # resubmit an unchanged result once a tempo, so the validator stays active


@dataclass(frozen=True)
class ChainView:
    network: str
    genesis_hash: str
    netuid: int
    finalized_block: int
    hotkey_to_uid: dict[str, int]
    owner_hotkey: str


class Source(Protocol):
    def latest(self) -> dict: ...


class Chain(Protocol):
    def view(self) -> ChainView: ...


class Submitter(Protocol):
    hotkey: str

    def submit(self, uids: list[int], weights: list[int], version_key: int, document_hash: str) -> dict: ...


@dataclass
class State:
    """What this validator last submitted, kept on disk so a restart does not resubmit at once."""

    path: Path | None = None
    document_hash: str | None = None
    block: int | None = None

    @classmethod
    def load(cls, path: Path) -> State:
        try:
            d = json.loads(path.read_text())
            return cls(path, d.get("document_hash"), d.get("block"))
        except (FileNotFoundError, ValueError):
            return cls(path)

    def save(self) -> None:
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"document_hash": self.document_hash, "block": self.block}))


@dataclass(frozen=True)
class Outcome:
    action: str  # submitted | up_to_date | refused | unavailable | failed
    reason: str
    detail: dict[str, Any]


Verify = Callable[[str, bytes, bytes], bool]


def run_cycle(
    source: Source, chain: Chain, submitter: Submitter, state: State, pin: str, verify: Verify
) -> Outcome:
    try:
        signed = source.latest()
    except Exception as e:  # noqa: BLE001 - any failure to fetch means no result this cycle
        return Outcome("unavailable", "the owner's weight result could not be fetched", {"error": str(e)})
    if signed.get("signer") != pin:
        return Outcome(
            "refused", "the result is not signed by the pinned owner key", {"signer": signed.get("signer")}
        )
    doc = signed["document"]
    try:
        sig = bytes.fromhex(str(signed["signature"]).removeprefix("0x"))
    except ValueError:
        return Outcome("refused", "the signature is not valid hex", {})
    if not verify(pin, signed_bytes(doc), sig):
        return Outcome("refused", "the signature does not match the document", {})
    view = chain.view()
    problems = check_document(
        doc,
        network=view.network,
        genesis_hash=view.genesis_hash,
        netuid=view.netuid,
        finalized_block=view.finalized_block,
    )
    if problems:
        return Outcome("refused", "the result does not fit this chain", {"problems": problems})
    if doc["burn_hotkey"] != view.owner_hotkey:
        return Outcome(
            "refused", "the burn hotkey is not this subnet's owner", {"burn_hotkey": doc["burn_hotkey"]}
        )
    if submitter.hotkey not in view.hotkey_to_uid:
        return Outcome("refused", "this validator's hotkey is not registered on the subnet", {})
    try:
        uids, weights, notes = chain_weights(doc, view.hotkey_to_uid)
    except WeightDocumentError as e:
        return Outcome("refused", str(e), {})
    h = document_hash(doc)
    if (
        state.document_hash == h
        and state.block is not None
        and view.finalized_block - state.block < RESUBMIT_BLOCKS
    ):
        return Outcome(
            "up_to_date", "these weights were already submitted this tempo", {"block": state.block}
        )
    result = submitter.submit(uids, weights, int(doc["weights_version_key"]), h)
    if not result.get("ok"):
        return Outcome("failed", "the chain refused the weights", {"error": result.get("error")})
    state.document_hash, state.block = h, int(result["block_number"])
    state.save()
    return Outcome(
        "submitted",
        f"weights for champion v{doc['champion_version']} submitted",
        {"block": state.block, "uids": uids, "weights": weights, "notes": notes, "document_hash": h},
    )
