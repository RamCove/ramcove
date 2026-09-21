"""Compute booked for paid admissions.

A paid admission books its screening and one evaluation (quality, up to two capacity readings and the GPU
check); each part is released as soon as it finishes. Queue capacity counts these bookings against what the
ready workers can deliver over the published horizon. A winner's extra checks and the new champion's
calibration come out of the published reserve. All quantities are centi-GPU-hours (integers).
"""

from __future__ import annotations

from dataclasses import dataclass

from .rules import StageEnvelope
from .state import S


def remaining_envelope(state: S, env: StageEnvelope) -> int:
    table = {
        S.QUOTED: env.total(),
        S.ADMITTED: env.total(),
        S.SCREENING: env.total(),
        S.EVAL_QUEUED: env.evaluation,
        S.EVALUATING: env.evaluation,
    }
    return table.get(state, 0)


@dataclass(frozen=True)
class CapacityPlan:
    workers_ready: int
    horizon_hours: int
    availability_bp: int = 8000  # the rest is the reserve: winners' checks, new champion scores, downtime

    def capacity_centi(self) -> int:
        return max(0, self.workers_ready * self.horizon_hours * 100 * self.availability_bp // 10_000)


@dataclass(frozen=True)
class QuoteCapacityCheck:
    allowed: bool
    committed_centi: int
    capacity_centi: int
    requested_centi: int
    reason: str


def can_issue_quote(
    committed_centi: int, env: StageEnvelope, plan: CapacityPlan, intake_paused: bool
) -> QuoteCapacityCheck:
    cap = plan.capacity_centi()
    req = env.total()
    if intake_paused:
        return QuoteCapacityCheck(False, committed_centi, cap, req, "intake is paused by the operator")
    if plan.workers_ready <= 0:
        return QuoteCapacityCheck(False, committed_centi, cap, req, "no evaluation worker is safe and ready")
    if committed_centi + req > cap:
        return QuoteCapacityCheck(
            False,
            committed_centi,
            cap,
            req,
            "published evaluation capacity is fully reserved; join the free waiting list",
        )
    return QuoteCapacityCheck(True, committed_centi, cap, req, "capacity reserved")
