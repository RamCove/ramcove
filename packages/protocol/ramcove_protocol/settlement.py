"""Promotion order and champion compare-and-set preconditions.

Promise: *promotion order is admission order*. A later admission can never be promoted while any
earlier admission in the same profile is still active and retains priority, whatever stage it
is in (screening, evaluation, reproduction, flagged review or awaiting registration). Priority is lost
only at a terminal state; every stage runs on a lease that is retried once and then ends as an operator
failure, so the barrier always releases.

Dispatch order (who starts work), completion order (who finishes first) and promotion order are
different things; only the last carries the fairness promise.
"""

from __future__ import annotations

from dataclasses import dataclass

from .state import ACTIVE, S


@dataclass(frozen=True)
class AdmissionKey:
    block: int
    extrinsic_index: int

    def __lt__(self, other: AdmissionKey) -> bool:
        return (self.block, self.extrinsic_index) < (other.block, other.extrinsic_index)


@dataclass(frozen=True)
class QueueEntry:
    submission_id: str
    profile_id: str
    key: AdmissionKey
    state: S
    compared_champion_version: int | None
    compared_rule_hash: str | None
    hotkey_registered: bool


@dataclass(frozen=True)
class PromotionDecision:
    allowed: bool
    blocking: tuple[str, ...]
    reason: str
    action: str  # "promote" | "wait" | "recompare" | "expire_registration" | "none"


def blockers_for(entry: QueueEntry, all_entries: list[QueueEntry]) -> list[QueueEntry]:
    return sorted(
        (
            e
            for e in all_entries
            if e.profile_id == entry.profile_id
            and e.submission_id != entry.submission_id
            and e.key < entry.key
            and e.state in ACTIVE
        ),
        key=lambda e: e.key,
    )


def decide_promotion(
    entry: QueueEntry,
    all_entries: list[QueueEntry],
    current_champion_version: int,
    current_rule_hash: str,
    registration_expired: bool,
) -> PromotionDecision:
    if entry.state != S.READY_FOR_PROMOTION:
        return PromotionDecision(False, (), f"state is {entry.state}", "none")
    if (
        entry.compared_champion_version != current_champion_version
        or entry.compared_rule_hash != current_rule_hash
    ):
        return PromotionDecision(
            False, (), "measured against an earlier champion: re-compare with the current one", "recompare"
        )
    blockers = blockers_for(entry, all_entries)
    if blockers:
        return PromotionDecision(
            False,
            tuple(b.submission_id for b in blockers),
            f"{len(blockers)} earlier admission(s) still hold priority",
            "wait",
        )
    if not entry.hotkey_registered:
        if registration_expired:
            return PromotionDecision(
                False, (), "hotkey not registered before the grace period ended", "expire_registration"
            )
        return PromotionDecision(
            False, (), "waiting for hotkey registration; incumbent keeps its allocation", "wait"
        )
    return PromotionDecision(
        True, (), "all earlier admissions settled; evidence current; hotkey registered", "promote"
    )
