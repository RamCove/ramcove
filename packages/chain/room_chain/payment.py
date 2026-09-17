"""Verification of a ROOM evaluation-fee payment (Section 6.3, verified runtime design).

Expected extrinsic, signed by the authorized payer:
    Utility.batch_all([Balances.transfer_keep_alive(dest=<wallet>, value=<fee>),
                       System.remark_with_event(remark=b"room:quote:<quote_id>")])

Checks, all against events whose ApplyExtrinsic phase index equals this extrinsic's index:
finalized canonical block; outer ``System.ExtrinsicSuccess``; ``Utility.BatchCompleted`` and no
``BatchInterrupted``; ``Balances.Transfer`` from payer to wallet; ``System.Remarked`` whose hash is
blake2_256 of the remark bytes carried in the call body; quote binding and expiry; unused reference.
The runtime (spec 464, test and finney) exposes these calls/events; see docs/adr/0004.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from .types import Extrinsic, FinalizedHead

REMARK_PREFIX = b"room:quote:"
TRANSFER_FUNCTIONS = {"transfer_keep_alive"}


class Outcome(StrEnum):
    VERIFIED = "verified"
    NOT_FINALIZED = "not_finalized"          # observe again later; no decision
    REJECTED = "rejected"                    # not a valid payment for this quote
    LATE = "late"                            # valid transfer but finalized after quote expiry


@dataclass(frozen=True)
class QuoteTerms:
    quote_id: str
    payer: str
    recipient: str
    amount_rao: int
    expires_block: int
    network: str


@dataclass(frozen=True)
class PaymentVerdict:
    outcome: Outcome
    reason: str
    paid_rao: int = 0
    excess_rao: int = 0
    reference: tuple[str, int] | None = None
    refund_eligible: bool = False


def blake2_256(data: bytes) -> str:
    return "0x" + hashlib.blake2b(data, digest_size=32).hexdigest()


def _hex_to_bytes(v: object) -> bytes:
    if isinstance(v, bytes):
        return v
    if isinstance(v, str):
        return bytes.fromhex(v[2:]) if v.startswith("0x") else v.encode()
    raise ValueError("unsupported remark encoding")


def verify_payment(ext: Extrinsic, terms: QuoteTerms, head: FinalizedHead, canonical_hash_at: str | None,
                   used_references: set[tuple[str, int]], network: str) -> PaymentVerdict:
    ref = (ext.block_hash, ext.index)
    if network != terms.network:
        return PaymentVerdict(Outcome.REJECTED, "payment observed on a different network than the quote")
    if ext.block_number > head.number:
        return PaymentVerdict(Outcome.NOT_FINALIZED, "block is not finalized yet", reference=ref)
    if canonical_hash_at is None or canonical_hash_at.lower() != ext.block_hash.lower():
        return PaymentVerdict(Outcome.REJECTED, "block is not on the finalized canonical chain")
    if ref in used_references:
        return PaymentVerdict(Outcome.REJECTED, "payment reference was already used")
    c = ext.call
    if (c.module, c.function) != ("Utility", "batch_all"):
        return PaymentVerdict(Outcome.REJECTED, "payment must use Utility.batch_all (plain batch is refused)")
    if len(c.inner) != 2:
        return PaymentVerdict(Outcome.REJECTED, "batch_all must contain exactly a transfer and a remark")
    transfer, remark = c.inner
    if transfer.module != "Balances" or transfer.function not in TRANSFER_FUNCTIONS:
        return PaymentVerdict(Outcome.REJECTED, "first call must be Balances.transfer_keep_alive")
    if (remark.module, remark.function) != ("System", "remark_with_event"):
        return PaymentVerdict(Outcome.REJECTED, "second call must be System.remark_with_event")
    try:
        remark_bytes = _hex_to_bytes(remark.args.get("remark"))
    except ValueError:
        return PaymentVerdict(Outcome.REJECTED, "remark could not be decoded")
    if remark_bytes != REMARK_PREFIX + terms.quote_id.encode():
        return PaymentVerdict(Outcome.REJECTED, "remark does not carry this quote identifier")
    if ext.signer != terms.payer:
        return PaymentVerdict(Outcome.REJECTED, "signer is not the payer authorized in the quote", refund_eligible=True)

    own = [e for e in ext.events if e.extrinsic_index == ext.index]
    names = {(e.module, e.name) for e in own}
    if ("System", "ExtrinsicFailed") in names or ("System", "ExtrinsicSuccess") not in names:
        return PaymentVerdict(Outcome.REJECTED, "extrinsic did not succeed")
    if ("Utility", "BatchInterrupted") in names or ("Utility", "BatchCompleted") not in names:
        return PaymentVerdict(Outcome.REJECTED, "batch did not complete atomically")
    transfers = [e for e in own if (e.module, e.name) == ("Balances", "Transfer")
                 and e.attributes.get("from") == terms.payer and e.attributes.get("to") == terms.recipient]
    if len(transfers) != 1:
        return PaymentVerdict(Outcome.REJECTED, "no single transfer from the payer to the evaluation wallet")
    call_dest = transfer.args.get("dest")
    call_value = int(transfer.args.get("value", -1))
    paid = int(transfers[0].attributes.get("amount", 0))
    if call_dest != terms.recipient or call_value != paid:
        return PaymentVerdict(Outcome.REJECTED, "transfer call and transfer event disagree")
    remarked = [e for e in own if (e.module, e.name) == ("System", "Remarked")]
    if len(remarked) != 1 or str(remarked[0].attributes.get("hash", "")).lower() != blake2_256(remark_bytes) \
            or remarked[0].attributes.get("sender") != terms.payer:
        return PaymentVerdict(Outcome.REJECTED, "remark event does not match the remark bytes and payer")
    if paid < terms.amount_rao:
        return PaymentVerdict(Outcome.REJECTED, f"underpaid: {paid} rao < {terms.amount_rao} rao", paid, 0, ref, True)
    excess = paid - terms.amount_rao
    if ext.block_number > terms.expires_block:
        return PaymentVerdict(Outcome.LATE, "payment finalized after the quote expired", paid, excess, ref, True)
    return PaymentVerdict(Outcome.VERIFIED, "payment verified", paid, excess, ref)
