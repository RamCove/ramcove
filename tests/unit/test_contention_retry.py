"""Lock contention is retried where that is safe, and never reported as an internal fault."""

from __future__ import annotations

import pytest
from psycopg.errors import DeadlockDetected, LockNotAvailable, UndefinedTable
from ramcove_api.store.db import is_contention, retry_on_contention
from sqlalchemy.exc import OperationalError


def contention(kind=LockNotAvailable) -> OperationalError:
    return OperationalError(
        "SELECT pg_advisory_xact_lock(...)", {}, kind("canceling statement due to lock timeout")
    )


def test_contention_is_recognised_and_other_errors_are_not():
    assert is_contention(contention(LockNotAvailable))
    assert is_contention(contention(DeadlockDetected))
    assert not is_contention(OperationalError("SELECT 1", {}, UndefinedTable("no such table")))
    assert not is_contention(ValueError("not a database error"))


def test_a_lost_lock_race_is_retried_until_it_succeeds():
    calls = []

    @retry_on_contention(attempts=4)
    def admit():
        calls.append(1)
        if len(calls) < 3:
            raise contention()
        return "admitted"

    assert admit() == "admitted"
    assert len(calls) == 3


def test_retries_stop_after_the_last_attempt_and_the_error_surfaces():
    calls = []

    @retry_on_contention(attempts=3)
    def always_busy():
        calls.append(1)
        raise contention(DeadlockDetected)

    with pytest.raises(OperationalError):
        always_busy()
    assert len(calls) == 3


def test_other_database_errors_are_not_retried():
    calls = []

    @retry_on_contention(attempts=4)
    def broken():
        calls.append(1)
        raise OperationalError("SELECT 1", {}, UndefinedTable("no such table"))

    with pytest.raises(OperationalError):
        broken()
    assert calls == [1]
