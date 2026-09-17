"""Proposed weight plan (Section 8.3, prompt C). Pure and deterministic.

The plan is a *recommendation* keyed by hotkey. The chain adapter resolves hotkeys to UIDs at
publication time; realized emissions depend on consensus and are displayed separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

U16_MAX = 65_535


@dataclass(frozen=True)
class ChampionState:
    profile_id: str
    champion_version: int
    author_hotkey: str | None      # None for champion version 0 (tuned stack, no author)
    eligible: bool
    suspended: bool


@dataclass(frozen=True)
class UidSnapshot:
    block: int
    netuid: int
    hotkey_to_uid: dict[str, int]
    owner_hotkey: str


@dataclass(frozen=True)
class WeightEntry:
    hotkey: str
    uid: int
    weight_u16: int
    role: Literal["champion", "no_winner_owner_uid"]


@dataclass(frozen=True)
class WeightPlan:
    schema: str
    snapshot_block: int
    netuid: int
    entries: tuple[WeightEntry, ...]
    no_winner: bool
    writer_enabled: bool
    notes: tuple[str, ...]


def build_weight_plan(champions: list[ChampionState], allocation_bp: dict[str, int], snap: UidSnapshot,
                      no_winner_mechanism_verified: bool) -> WeightPlan:
    if sum(allocation_bp.values()) != 10_000:
        raise ValueError("profile allocations must sum to 10,000 basis points and be published in advance")
    notes: list[str] = []
    per_hotkey: dict[str, int] = {}
    no_winner_bp = 0
    for ch in sorted(champions, key=lambda c: c.profile_id):
        share = allocation_bp.get(ch.profile_id, 0)
        hk = ch.author_hotkey
        if hk and ch.eligible and not ch.suspended and hk in snap.hotkey_to_uid:
            per_hotkey[hk] = per_hotkey.get(hk, 0) + share
        else:
            if hk and hk not in snap.hotkey_to_uid:
                notes.append(f"{ch.profile_id}: champion hotkey is not registered at block {snap.block}; share not paid")
            no_winner_bp += share
    entries = [WeightEntry(hk, snap.hotkey_to_uid[hk], bp * U16_MAX // 10_000, "champion")
               for hk, bp in sorted(per_hotkey.items())]
    if no_winner_bp:
        owner_uid = snap.hotkey_to_uid.get(snap.owner_hotkey)
        if owner_uid is None:
            raise ValueError("owner hotkey is not in the UID snapshot")
        entries.append(WeightEntry(snap.owner_hotkey, owner_uid, no_winner_bp * U16_MAX // 10_000,
                                   "no_winner_owner_uid"))
        notes.append("no-winner share is proposed for the owner UID; burn behaviour must be verified on the target runtime")
    writer_enabled = no_winner_bp == 0 or no_winner_mechanism_verified
    if not writer_enabled:
        notes.append("weight writer disabled: no-winner mechanism not yet verified on testnet")
    return WeightPlan("room.weight_plan/1", snap.block, snap.netuid, tuple(entries), no_winner_bp == 10_000,
                      writer_enabled, tuple(notes))
