"""Submission lifecycle state machine (explicit, versioned ``room.lifecycle/1``).

Every transition is named; the database layer applies them inside transactions with row locks.
Terminal states never transition again.
"""

from __future__ import annotations

from enum import StrEnum


class S(StrEnum):
    # free, unpaid
    PREFLIGHT_PASSED = "preflight_passed"
    WAITLISTED = "waitlisted"
    INVITED = "invited"
    # paid admission
    QUOTED = "quoted"
    ADMITTED = "admitted"          # verified finalized payment, receipt issued
    SCREENING = "screening"
    EVAL_QUEUED = "eval_queued"
    EVALUATING = "evaluating"
    CONFIRM_QUEUED = "confirm_queued"
    CONFIRMING = "confirming"
    IN_REVIEW = "in_review"
    READY_FOR_PROMOTION = "ready_for_promotion"   # technically approved; waiting registration and order
    # terminal
    PROMOTED = "promoted"
    NOT_PROMOTED = "not_promoted"                 # evaluated/confirmed but did not clear the rule
    REJECTED_PREFLIGHT = "rejected_preflight"
    REJECTED_SCREEN = "rejected_screen"
    REVIEW_REJECTED = "review_rejected"
    EXPIRED_QUOTE = "expired_quote"
    EXPIRED_UNREGISTERED = "expired_unregistered"
    OPERATOR_FAILED = "operator_failed"           # infra/quorum/deadline failure: refund or credit
    WITHDRAWN = "withdrawn"


TERMINAL = frozenset({
    S.PROMOTED, S.NOT_PROMOTED, S.REJECTED_PREFLIGHT, S.REJECTED_SCREEN, S.REVIEW_REJECTED,
    S.EXPIRED_QUOTE, S.EXPIRED_UNREGISTERED, S.OPERATOR_FAILED, S.WITHDRAWN,
})

PAID_ACTIVE = frozenset({
    S.ADMITTED, S.SCREENING, S.EVAL_QUEUED, S.EVALUATING, S.CONFIRM_QUEUED, S.CONFIRMING,
    S.IN_REVIEW, S.READY_FOR_PROMOTION,
})

# event name -> {from_state: to_state}
TRANSITIONS: dict[str, dict[S, S]] = {
    "waitlist": {S.PREFLIGHT_PASSED: S.WAITLISTED},
    "invite": {S.WAITLISTED: S.INVITED},
    "quote": {S.PREFLIGHT_PASSED: S.QUOTED, S.INVITED: S.QUOTED},
    "invitation_missed": {S.INVITED: S.WAITLISTED},
    "quote_expired": {S.QUOTED: S.EXPIRED_QUOTE},
    "payment_verified": {S.QUOTED: S.ADMITTED},
    "screen_start": {S.ADMITTED: S.SCREENING},
    "screen_pass": {S.SCREENING: S.EVAL_QUEUED},
    "screen_decisive_fail": {S.SCREENING: S.REJECTED_SCREEN},
    "eval_start": {S.EVAL_QUEUED: S.EVALUATING},
    "eval_not_potential": {S.EVALUATING: S.NOT_PROMOTED},
    "eval_potential": {S.EVALUATING: S.CONFIRM_QUEUED},
    "confirm_start": {S.CONFIRM_QUEUED: S.CONFIRMING},
    "confirm_fail": {S.CONFIRMING: S.NOT_PROMOTED},
    "confirm_pass": {S.CONFIRMING: S.IN_REVIEW},
    "review_approve": {S.IN_REVIEW: S.READY_FOR_PROMOTION},
    "review_reject": {S.IN_REVIEW: S.REVIEW_REJECTED},
    "appeal_upheld": {S.REVIEW_REJECTED: S.IN_REVIEW},
    "promote": {S.READY_FOR_PROMOTION: S.PROMOTED},
    "registration_expired": {S.READY_FOR_PROMOTION: S.EXPIRED_UNREGISTERED},
    # lease expiry keeps admission priority: back to the queue of the same stage
    "lease_expired": {S.SCREENING: S.ADMITTED, S.EVALUATING: S.EVAL_QUEUED, S.CONFIRMING: S.CONFIRM_QUEUED},
    # champion changed before promotion: fresh evidence against the new champion, same key, no fee
    "rebase": {S.CONFIRM_QUEUED: S.CONFIRM_QUEUED, S.CONFIRMING: S.CONFIRM_QUEUED, S.IN_REVIEW: S.CONFIRM_QUEUED,
               S.READY_FOR_PROMOTION: S.CONFIRM_QUEUED, S.EVAL_QUEUED: S.EVAL_QUEUED,
               S.EVALUATING: S.EVAL_QUEUED},
    "operator_failure": {s: S.OPERATOR_FAILED for s in PAID_ACTIVE},
    "withdraw": {**{s: S.WITHDRAWN for s in PAID_ACTIVE if s != S.READY_FOR_PROMOTION},
                 S.PREFLIGHT_PASSED: S.WITHDRAWN, S.WAITLISTED: S.WITHDRAWN, S.INVITED: S.WITHDRAWN,
                 S.QUOTED: S.WITHDRAWN},
}


class TransitionError(ValueError):
    pass


def next_state(current: S | str, event: str) -> S:
    cur = S(current)
    if cur in TERMINAL and event != "appeal_upheld":
        raise TransitionError(f"{cur} is terminal")
    table = TRANSITIONS.get(event)
    if table is None:
        raise TransitionError(f"unknown event {event}")
    if cur not in table:
        raise TransitionError(f"event {event} not allowed from {cur}")
    return table[cur]


def fee_outcome(terminal: S) -> str:
    """Published fee rule for each terminal state (Section 6.3 table, review R4)."""
    return {
        S.PROMOTED: "consumed",
        S.NOT_PROMOTED: "consumed",
        S.REJECTED_SCREEN: "consumed",
        S.REVIEW_REJECTED: "consumed",
        S.EXPIRED_UNREGISTERED: "consumed",
        S.OPERATOR_FAILED: "refund_or_credit",
        S.WITHDRAWN: "withdrawal_policy",
        S.EXPIRED_QUOTE: "none_or_late_payment_refund",
        S.REJECTED_PREFLIGHT: "none",
    }[terminal]


def withdrawal_fee_outcome(state_before: S | str) -> str:
    """Miner withdrawal: before any GPU work starts the fee returns as credit; afterwards it is consumed
    unless the operator missed a published deadline (then operator_failure applies instead)."""
    st = S(state_before)
    if st in (S.PREFLIGHT_PASSED, S.WAITLISTED, S.INVITED, S.QUOTED):
        return "none"
    if st == S.ADMITTED:
        return "credit"
    return "consumed"
