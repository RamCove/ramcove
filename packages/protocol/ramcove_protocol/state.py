"""Submission lifecycle state machine (explicit, versioned ``ramcove.lifecycle/2``).

Submitting is free: a submission that passes the free checks is admitted to the queue when evaluation
capacity is free, or waits on the free waiting list until it is invited.

Every transition is named; the database layer applies them inside transactions with row locks.
Terminal states never transition again.
"""

from __future__ import annotations

from enum import StrEnum


class S(StrEnum):
    # free checks passed, not yet in the queue
    PREFLIGHT_PASSED = "preflight_passed"
    WAITLISTED = "waitlisted"
    INVITED = "invited"
    # in the queue
    ADMITTED = "admitted"  # capacity reserved and admission key assigned
    SCREENING = "screening"
    EVAL_QUEUED = "eval_queued"
    EVALUATING = "evaluating"
    # only when the profile sets reproduce_winners: another evaluation group repeats a winning reading
    REPRODUCE_QUEUED = "reproduce_queued"
    REPRODUCING = "reproducing"
    IN_REVIEW = "in_review"  # only when an automatic check flags the winner
    READY_FOR_PROMOTION = "ready_for_promotion"  # technically approved; waiting registration and order
    # terminal
    PROMOTED = "promoted"
    NOT_PROMOTED = "not_promoted"  # evaluated but did not clear the rule
    REJECTED_PREFLIGHT = "rejected_preflight"
    REJECTED_SCREEN = "rejected_screen"
    REVIEW_REJECTED = "review_rejected"
    EXPIRED_UNREGISTERED = "expired_unregistered"
    OPERATOR_FAILED = "operator_failed"  # repeated infrastructure or quorum failure
    WITHDRAWN = "withdrawn"


TERMINAL = frozenset(
    {
        S.PROMOTED,
        S.NOT_PROMOTED,
        S.REJECTED_PREFLIGHT,
        S.REJECTED_SCREEN,
        S.REVIEW_REJECTED,
        S.EXPIRED_UNREGISTERED,
        S.OPERATOR_FAILED,
        S.WITHDRAWN,
    }
)

# admitted and not yet finished: these hold evaluation capacity and a place in the queue
ACTIVE = frozenset(
    {
        S.ADMITTED,
        S.SCREENING,
        S.EVAL_QUEUED,
        S.EVALUATING,
        S.REPRODUCE_QUEUED,
        S.REPRODUCING,
        S.IN_REVIEW,
        S.READY_FOR_PROMOTION,
    }
)

# measured and waiting on promotion: these are re-compared when the champion changes
AWAITING_PROMOTION = frozenset({S.REPRODUCE_QUEUED, S.REPRODUCING, S.IN_REVIEW, S.READY_FOR_PROMOTION})

# event name -> {from_state: to_state}
TRANSITIONS: dict[str, dict[S, S]] = {
    "waitlist": {S.PREFLIGHT_PASSED: S.WAITLISTED},
    "invite": {S.WAITLISTED: S.INVITED},
    "admit": {S.PREFLIGHT_PASSED: S.ADMITTED, S.INVITED: S.ADMITTED},
    "invitation_missed": {S.INVITED: S.WAITLISTED},
    "screen_start": {S.ADMITTED: S.SCREENING},
    "screen_pass": {S.SCREENING: S.EVAL_QUEUED},
    "screen_decisive_fail": {S.SCREENING: S.REJECTED_SCREEN},
    "eval_start": {S.EVAL_QUEUED: S.EVALUATING},
    "eval_lose": {S.EVALUATING: S.NOT_PROMOTED},
    "eval_win": {S.EVALUATING: S.READY_FOR_PROMOTION},
    "eval_win_flagged": {S.EVALUATING: S.IN_REVIEW},
    "eval_win_reproduce": {S.EVALUATING: S.REPRODUCE_QUEUED},
    "reproduce_start": {S.REPRODUCE_QUEUED: S.REPRODUCING},
    "reproduce_fail": {S.REPRODUCING: S.NOT_PROMOTED},
    "reproduce_pass": {S.REPRODUCING: S.READY_FOR_PROMOTION},
    "reproduce_pass_flagged": {S.REPRODUCING: S.IN_REVIEW},
    "review_approve": {S.IN_REVIEW: S.READY_FOR_PROMOTION},
    "review_reject": {S.IN_REVIEW: S.REVIEW_REJECTED},
    "appeal_upheld": {S.REVIEW_REJECTED: S.IN_REVIEW},
    "promote": {S.READY_FOR_PROMOTION: S.PROMOTED},
    "registration_expired": {S.READY_FOR_PROMOTION: S.EXPIRED_UNREGISTERED},
    # lease expiry keeps admission priority: back to the queue of the same stage
    "lease_expired": {
        S.SCREENING: S.ADMITTED,
        S.EVALUATING: S.EVAL_QUEUED,
        S.REPRODUCING: S.REPRODUCE_QUEUED,
    },
    # a new champion was crowned first: the measured gain is re-compared with the new champion's score, and a
    # challenger that no longer clears the margin ends here (no new measurement)
    "recompare_lose": {s: S.NOT_PROMOTED for s in AWAITING_PROMOTION},
    # emergency rollback: pending work is evaluated again against the restored stack, same key
    "requeue": {
        S.EVAL_QUEUED: S.EVAL_QUEUED,
        S.EVALUATING: S.EVAL_QUEUED,
        **{s: S.EVAL_QUEUED for s in AWAITING_PROMOTION},
    },
    "operator_failure": {s: S.OPERATOR_FAILED for s in ACTIVE},
    "withdraw": {
        **{s: S.WITHDRAWN for s in ACTIVE if s != S.READY_FOR_PROMOTION},
        S.PREFLIGHT_PASSED: S.WITHDRAWN,
        S.WAITLISTED: S.WITHDRAWN,
        S.INVITED: S.WITHDRAWN,
    },
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
