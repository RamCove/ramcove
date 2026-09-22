"""The owner's question bank: periods, identifiers and seeds (Section 8.7). Pure arithmetic, no I/O.

The owner platform holds one secret. Each period's seed is an HMAC of that secret with the profile and the
period number, so seeds cannot be guessed ahead of time, yet revealing one period's seed says nothing about
any other period's.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

from .rules import QuestionBankRule


def epoch_start(rule: QuestionBankRule) -> datetime:
    return datetime.fromisoformat(rule.epoch.replace("Z", "+00:00")).astimezone(UTC)


def period_index(rule: QuestionBankRule, at: datetime) -> int:
    return int((at - epoch_start(rule)) // timedelta(days=rule.period_days))


def period_window(rule: QuestionBankRule, index: int) -> tuple[datetime, datetime]:
    start = epoch_start(rule) + index * timedelta(days=rule.period_days)
    return start, start + timedelta(days=rule.period_days)


def bank_id(profile_id: str, index: int) -> str:
    return f"{profile_id}:bank:{index}"


def period_seed(secret: bytes, profile_id: str, index: int) -> str:
    return hmac.new(secret, f"ramcove.bank/1:{profile_id}:{index}".encode(), hashlib.sha256).hexdigest()
