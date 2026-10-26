"""Proposed weight plan (Section 9.3). Pure and deterministic.

King of the hill: every profile keeps a queue of up to ``KING_SLOTS`` kings. King #1 is the current
champion, the stack every challenger must beat. When a challenger beats King #1 it becomes the new
King #1, every king moves down one place, and King #5 leaves the queue and is paid no longer. Each slot
carries an equal share of the profile's miner allocation (20% with five slots). A slot that is empty, or
whose king is ineligible or not registered, is proposed for the owner UID, where it is burned.

The plan is a *recommendation* keyed by hotkey. The chain adapter resolves hotkeys to UIDs at
publication time; realized emissions depend on consensus and are displayed separately.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

U16_MAX = 65_535
KING_SLOTS = 5


class ChampionRecord(Protocol):
    version: int
    submission_id: str | None
    author_hotkey: str | None
    status: str


def select_kings[R: ChampionRecord](records: Sequence[R], current_version: int) -> list[R]:
    """The king queue, read from a profile's champion history: King #1 first.

    King #1 is the current champion. Below it come the champions it displaced, newest first, up to
    ``KING_SLOTS`` in all, so the oldest falls off when a new king is crowned. A rolled-back champion leaves
    the queue, and the stack restored in its place (a new version of the same submission) is not counted
    twice, so the kings below move up. The tuned baseline has no author and is never a king."""
    current = next((r for r in records if r.version == current_version), None)
    if current is None or current.author_hotkey is None:
        return []
    kings: list[R] = []
    seen: set[str] = set()
    for r in sorted(records, key=lambda r: r.version, reverse=True):
        if r.version > current_version or r.author_hotkey is None or r.status == "rolled_back":
            continue
        key = r.submission_id or f"version-{r.version}"
        if key in seen:
            continue
        seen.add(key)
        kings.append(r)
        if len(kings) == KING_SLOTS:
            break
    return kings


@dataclass(frozen=True)
class KingState:
    profile_id: str
    slot: int  # 1 is the current champion; 2..KING_SLOTS are the kings it displaced, newest first
    champion_version: int
    author_hotkey: str
    eligible: bool  # False while suspended, retired or excluded


@dataclass(frozen=True)
class UidSnapshot:
    block: int
    netuid: int
    hotkey_to_uid: dict[str, int]
    owner_hotkey: str


@dataclass(frozen=True)
class KingSlot:
    profile_id: str
    slot: int
    champion_version: int | None
    hotkey: str | None
    share_bp: int
    paid: bool
    reason: Literal["paid", "empty", "ineligible", "not_registered"]


@dataclass(frozen=True)
class WeightEntry:
    hotkey: str
    uid: int
    weight_u16: int
    role: Literal["king", "burn"]


@dataclass(frozen=True)
class WeightPlan:
    schema: str
    snapshot_block: int
    netuid: int
    entries: tuple[WeightEntry, ...]
    kings: tuple[KingSlot, ...]
    no_winner: bool
    writer_enabled: bool
    notes: tuple[str, ...]


def build_weight_plan(
    kings: list[KingState],
    allocation_bp: dict[str, int],
    snap: UidSnapshot,
    no_winner_mechanism_verified: bool,
) -> WeightPlan:
    if sum(allocation_bp.values()) != 10_000:
        raise ValueError("profile allocations must sum to 10,000 basis points and be published in advance")
    by_profile: dict[str, dict[int, KingState]] = {}
    for k in kings:
        if not 1 <= k.slot <= KING_SLOTS:
            raise ValueError(f"{k.profile_id}: king slot {k.slot} is outside 1..{KING_SLOTS}")
        if k.slot in by_profile.setdefault(k.profile_id, {}):
            raise ValueError(f"{k.profile_id}: two kings in slot {k.slot}")
        by_profile[k.profile_id][k.slot] = k
    notes: list[str] = []
    per_hotkey: dict[str, int] = {}
    slots: list[KingSlot] = []
    burn_bp = 0
    for profile_id in sorted(allocation_bp):
        share = allocation_bp[profile_id]
        per_slot = share // KING_SLOTS
        burn_bp += share - per_slot * KING_SLOTS  # rounding remainder, if the share does not divide evenly
        queue = by_profile.get(profile_id, {})
        for slot in range(1, KING_SLOTS + 1):
            k = queue.get(slot)
            if k is None:
                burn_bp += per_slot
                slots.append(KingSlot(profile_id, slot, None, None, per_slot, False, "empty"))
            elif not k.eligible:
                burn_bp += per_slot
                slots.append(
                    KingSlot(
                        profile_id, slot, k.champion_version, k.author_hotkey, per_slot, False, "ineligible"
                    )
                )
            elif k.author_hotkey not in snap.hotkey_to_uid:
                burn_bp += per_slot
                notes.append(
                    f"{profile_id}: king #{slot} is not registered at block {snap.block}; its share is not paid"
                )
                slots.append(
                    KingSlot(
                        profile_id,
                        slot,
                        k.champion_version,
                        k.author_hotkey,
                        per_slot,
                        False,
                        "not_registered",
                    )
                )
            else:
                per_hotkey[k.author_hotkey] = per_hotkey.get(k.author_hotkey, 0) + per_slot
                slots.append(
                    KingSlot(profile_id, slot, k.champion_version, k.author_hotkey, per_slot, True, "paid")
                )
    entries = [
        WeightEntry(hk, snap.hotkey_to_uid[hk], bp * U16_MAX // 10_000, "king")
        for hk, bp in sorted(per_hotkey.items())
    ]
    if burn_bp:
        owner_uid = snap.hotkey_to_uid.get(snap.owner_hotkey)
        if owner_uid is None:
            raise ValueError("owner hotkey is not in the UID snapshot")
        entries.append(WeightEntry(snap.owner_hotkey, owner_uid, burn_bp * U16_MAX // 10_000, "burn"))
        notes.append(
            "the share of empty or unpaid king slots is proposed for the owner UID; burn behaviour must be "
            "verified on the target runtime"
        )
    writer_enabled = burn_bp == 0 or no_winner_mechanism_verified
    if not writer_enabled:
        notes.append("weight writer disabled: no-winner mechanism not yet verified on testnet")
    return WeightPlan(
        "ramcove.weight_plan/2",
        snap.block,
        snap.netuid,
        tuple(entries),
        tuple(slots),
        burn_bp == 10_000,
        writer_enabled,
        tuple(notes),
    )
