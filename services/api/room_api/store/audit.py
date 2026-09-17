"""Append-only, hash-chained audit log. A database trigger forbids UPDATE, DELETE and TRUNCATE.

The chain makes silent edits detectable; it does not prove that the recorded decisions were fair.
"""

from __future__ import annotations

from typing import Any

from room_protocol.canonical import record_hash
from sqlalchemy import Connection, select

from .db import advisory_lock, now
from .schema import audit_events

GENESIS = "0" * 64


def append(
    conn: Connection,
    actor: str,
    action: str,
    subject_type: str,
    subject_id: str,
    data: dict[str, Any] | None = None,
    public: bool = False,
) -> str:
    advisory_lock(conn, "audit-chain")
    prev = conn.execute(select(audit_events.c.hash).order_by(audit_events.c.id.desc()).limit(1)).scalar()
    at = now()
    body = {
        "at": at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "actor": actor,
        "action": action,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "data": data or {},
        "public": public,
        "prev_hash": prev or GENESIS,
    }
    h = record_hash(body)
    conn.execute(
        audit_events.insert().values(
            at=at,
            actor=actor,
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            data=data or {},
            public=public,
            prev_hash=prev or GENESIS,
            hash=h,
        )
    )
    return h


def verify_chain(conn: Connection) -> tuple[bool, int, str | None]:
    """Replay the audit chain. Returns (ok, events_checked, first_bad_event_id)."""
    prev = GENESIS
    n = 0
    for row in conn.execute(select(audit_events).order_by(audit_events.c.id)):
        body = {
            "at": row.at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "actor": row.actor,
            "action": row.action,
            "subject_type": row.subject_type,
            "subject_id": row.subject_id,
            "data": row.data,
            "public": row.public,
            "prev_hash": row.prev_hash,
        }
        if row.prev_hash != prev or record_hash(body) != row.hash:
            return False, n, str(row.id)
        prev = row.hash
        n += 1
    return True, n, None
