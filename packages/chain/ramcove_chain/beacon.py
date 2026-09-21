"""Randomness scheduling for capacity readings (Section 7.8).

A comparison record names a *future* beacon round chosen only after the record's anchor is
finalized. The seed is sha256(round randomness || comparison id). Fallback: if a round is
unavailable after ``max_wait_s``, use the next round (round + 1, then + 2 ...) up to
``max_fallback`` times, then void the reading with a published reason. No discretionary redraws.

Honest limits: the dev beacon is a deterministic SIMULATION. The drand HTTP reader fetches rounds
from public relays but this build does NOT verify drand BLS signatures (docs/adr/0006).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx

QUICKNET_CHAIN_HASH = "52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971"
QUICKNET_GENESIS = datetime(2023, 8, 23, 15, 9, 27, tzinfo=UTC)
QUICKNET_PERIOD_S = 3


@dataclass(frozen=True)
class BeaconRound:
    round: int
    randomness_hex: str
    simulated: bool
    signature_verified: bool


class Beacon(Protocol):
    def round_at(self, when: datetime) -> int: ...
    def fetch(self, round_: int) -> BeaconRound | None: ...


def schedule_round(beacon: Beacon, anchor_finalized_at: datetime, min_delay: timedelta) -> int:
    return beacon.round_at(anchor_finalized_at + min_delay) + 1


def comparison_seed(br: BeaconRound, comparison_id: str) -> str:
    return hashlib.sha256(bytes.fromhex(br.randomness_hex) + comparison_id.encode()).hexdigest()


@dataclass(frozen=True)
class RoundResolution:
    used_round: int | None
    seed: str | None
    void_reason: str | None
    attempts: tuple[int, ...]


def resolve_round(
    beacon: Beacon, scheduled: int, comparison_id: str, max_fallback: int = 3
) -> RoundResolution:
    tried = []
    for k in range(max_fallback + 1):
        r = scheduled + k
        tried.append(r)
        br = beacon.fetch(r)
        if br is not None:
            return RoundResolution(r, comparison_seed(br, comparison_id), None, tuple(tried))
    return RoundResolution(None, None, f"beacon rounds {tried} unavailable; reading voided", tuple(tried))


class DevBeacon:
    """Deterministic simulation: randomness = sha256('ramcove-dev-beacon:' + round)."""

    def __init__(
        self,
        genesis: datetime = QUICKNET_GENESIS,
        period_s: int = QUICKNET_PERIOD_S,
        missing_rounds: set[int] | None = None,
    ) -> None:
        self.genesis, self.period, self.missing = genesis, period_s, missing_rounds or set()

    def round_at(self, when: datetime) -> int:
        return int((when - self.genesis).total_seconds() // self.period) + 1

    def fetch(self, round_: int) -> BeaconRound | None:
        if round_ in self.missing:
            return None
        return BeaconRound(
            round_, hashlib.sha256(f"ramcove-dev-beacon:{round_}".encode()).hexdigest(), True, False
        )


class DrandHttpBeacon:
    def __init__(self, relays: list[str], timeout_s: float = 5.0) -> None:
        self.relays, self.timeout = relays, timeout_s

    def round_at(self, when: datetime) -> int:
        return int((when - QUICKNET_GENESIS).total_seconds() // QUICKNET_PERIOD_S) + 1

    def fetch(self, round_: int) -> BeaconRound | None:
        seen: set[str] = set()
        for relay in self.relays:
            try:
                r = httpx.get(f"{relay}/{QUICKNET_CHAIN_HASH}/public/{round_}", timeout=self.timeout)
                if r.status_code == 200:
                    seen.add(r.json()["randomness"])
            except (httpx.HTTPError, KeyError, ValueError):
                continue
        if len(seen) == 1:
            return BeaconRound(round_, seen.pop(), False, False)
        return None  # unavailable or relays disagree
