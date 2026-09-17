"""Engine and transaction helpers. All state changes run inside explicit transactions."""

from __future__ import annotations

import secrets
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import Connection, Engine, create_engine, text

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
