"""Conservative compute reservation (review R3).

The hard admission cap uses a worst-case *envelope* per paid admission, released stage by stage as
outcomes become known. Average pass rates are used only for forecasts shown as estimates.
All quantities are centi-GPU-hours (integers).
"""

from __future__ import annotations

from dataclasses import dataclass

from .rules import StageEnvelope
from .state import S


def remaining_envelope(state: S, env: StageEnvelope, rebases_used: int, max_rebases: int) -> int:
    rebase_left = max(0, max_rebases - rebases_used)
    confirm = env.confirmation_worst + env.rebase_allowance * min(1, rebase_left)
    tail = env.soak + env.recalibration_on_promotion
    table = {
        S.QUOTED: env.total(),
        S.ADMITTED: env.total(),
        S.SCREENING: env.total(),
        S.EVAL_QUEUED: env.full + confirm + tail,
        S.EVALUATING: env.full + confirm + tail,
        S.CONFIRM_QUEUED: confirm + tail,
        S.CONFIRMING: confirm + tail,
        S.IN_REVIEW: tail,
        S.READY_FOR_PROMOTION: env.recalibration_on_promotion,
    }
    return table.get(state, 0)


@dataclass(frozen=True)
class CapacityPlan:
    workers_ready: int
    horizon_hours: int
    availability_bp: int = 8500
    calibration_centi_per_worker_week: int = 1258

    def capacity_centi(self) -> int:
        weeks = self.horizon_hours / 168
        raw = self.workers_ready * self.horizon_hours * 100 * self.availability_bp // 10_000
        return max(0, int(raw - self.calibration_centi_per_worker_week * self.workers_ready * weeks))


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
