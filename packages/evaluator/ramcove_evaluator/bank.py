"""A period's question bank, built from its seed (Section 7.6).

The owner platform builds one secret bank per period (7 days in the first profile): the screening questions,
the offline quality questions and the traffic scripts the capacity readings play. Before the period starts it
publishes the bank's commitment, the hash of this module's manifest. Validators receive the period seed when
they take work in the period, so every evaluation in it answers the same questions; each capacity reading
also mixes in a drand seed nobody can know in advance, so the exact traffic of a reading stays unpredictable.
When the period ends the seed is revealed, and anyone can rebuild the bank here and check the commitment.

Because the questions are fixed for a period, the champion answers them once per worker per bank instead of
once per evaluation; its answers are packed into the worker's calibration record.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from functools import lru_cache

from ramcove_protocol.canonical import record_hash
from ramcove_protocol.rules import QuestionBankRule

from .taskgen import GENERATOR_VERSION, Item, offline_suite


@dataclass(frozen=True)
class Bank:
    bank_id: str
    seed: str
    screening: tuple[Item, ...]
    offline: tuple[Item, ...]

    @property
    def traffic_seed(self) -> str:
        """The bank's part of every reading's traffic; the reading's drand seed is mixed in on top."""
        return hashlib.sha256(f"{self.seed}:traffic".encode()).hexdigest()

    @property
    def answer_seed(self) -> str:
        """Simulator only: ties a stack's simulated answers to the bank, so it answers a bank the same way."""
        return f"{self.seed}:answers"

    def manifest(self) -> dict:
        def items_hash(items: tuple[Item, ...]) -> str:
            return record_hash([[i.item_id, i.group, i.band, i.kind, i.answer] for i in items])

        return {
            "schema": "ramcove.bank/1",
            "generator": GENERATOR_VERSION,
            "bank_id": self.bank_id,
            "screening": {"count": len(self.screening), "hash": items_hash(self.screening)},
            "offline": {"count": len(self.offline), "hash": items_hash(self.offline)},
            "traffic": hashlib.sha256(self.traffic_seed.encode()).hexdigest(),
        }

    def commitment(self) -> str:
        return record_hash(self.manifest())


def build_bank(bank_id: str, seed: str, rule: QuestionBankRule) -> Bank:
    return _build(
        bank_id, seed, rule.screening_long, rule.screening_general, rule.offline_long, rule.offline_general
    )


@lru_cache(maxsize=8)
def _build(bank_id: str, seed: str, s_long: int, s_general: int, o_long: int, o_general: int) -> Bank:
    return Bank(
        bank_id,
        seed,
        tuple(offline_suite(f"{seed}:screening", s_long, s_general)),
        tuple(offline_suite(f"{seed}:offline", o_long, o_general)),
    )


def pack_outcomes(outcomes: tuple[int, ...]) -> str:
    """Right/wrong per question as a bit string, base64: 4,000 answers take about 670 characters."""
    bits = bytearray((len(outcomes) + 7) // 8)
    for i, ok in enumerate(outcomes):
        if ok:
            bits[i // 8] |= 1 << (i % 8)
    return base64.b64encode(bytes(bits)).decode()


def unpack_outcomes(packed: str, count: int) -> tuple[int, ...]:
    bits = base64.b64decode(packed)
    return tuple((bits[i // 8] >> (i % 8)) & 1 for i in range(count))
