"""Engine and transaction helpers. All state changes run inside explicit transactions."""

from __future__ import annotations

import functools
import random
import secrets
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import ParamSpec, TypeVar

from psycopg.errors import DeadlockDetected, LockNotAvailable
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import OperationalError

P = ParamSpec("P")
R = TypeVar("R")

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def make_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=10, future=True)


@contextmanager
def tx(engine: Engine) -> Iterator[Connection]:
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'; SET LOCAL statement_timeout = '30s'"))
        yield conn


def advisory_lock(conn: Connection, name: str) -> None:
    """Transaction-scoped lock serializing a protocol-critical section (capacity, settlement, audit)."""
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:n))"), {"n": name})


def is_contention(error: BaseException) -> bool:
    """True when PostgreSQL cancelled a transaction to break a deadlock or a lock wait. Nothing from that
    transaction was committed, so the caller can safely run it again."""
    return isinstance(error, OperationalError) and isinstance(
        error.orig, (DeadlockDetected, LockNotAvailable)
    )


def retry_on_contention(attempts: int = 4) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Re-run a function whose whole effect is one transaction when it loses a lock race.

    The lock timeout stays short on purpose, so a burst of simultaneous requests fails closed rather than
    queueing forever. Retrying with jittered backoff turns that into a short wait for the caller. Only
    use this on functions that do all their writes inside a single ``tx``.
    """

    def decorate(fn: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            for attempt in range(attempts):
                try:
                    return fn(*args, **kwargs)
                except OperationalError as e:
                    if not is_contention(e) or attempt == attempts - 1:
                        raise
                    time.sleep(0.05 * 2**attempt + random.random() * 0.05)  # noqa: S311 - jitter, not security
            raise AssertionError("unreachable")

        return wrapper

    return decorate


def now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    """Sortable identifier: prefix + 10 chars of millisecond time + 10 random chars (Crockford base32)."""
    ms = int(time.time() * 1000)
    t = "".join(_CROCKFORD[(ms >> (5 * i)) & 31] for i in reversed(range(10)))
    r = "".join(secrets.choice(_CROCKFORD) for _ in range(10))
    return f"{prefix}_{t}{r}".lower()


def support_ref() -> str:
    return (
        "RM-"
        + "".join(secrets.choice(_CROCKFORD) for _ in range(4))
        + "-"
        + "".join(secrets.choice(_CROCKFORD) for _ in range(4))
    )
