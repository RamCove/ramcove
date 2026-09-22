"""The owner platform's question banks (whitepaper Section 8.7).

One secret bank per profile and period. Its commitment is recorded in the public audit log (anchored on-chain
with the log) at least a day before the period starts; validators receive the period seed with each job in the
period; the seed is revealed once the period has ended, so anyone can rebuild the bank and check it.
"""

from __future__ import annotations

from datetime import datetime

from ramcove_evaluator.bank import build_bank
from ramcove_protocol.bank import bank_id, period_index, period_seed, period_window
from ramcove_protocol.rules import ProfileVersion
from sqlalchemy import select, update
from sqlalchemy.engine import Connection

from ..store import audit
from ..store.db import now
from ..store.schema import question_banks
from .context import AppContext, ServiceError


def _secret(ctx: AppContext) -> bytes:
    if not ctx.settings.bank_secret:
        raise ServiceError(
            "no_bank_secret", "the owner's question-bank secret is not configured; no bank can be issued", 503
        )
    return ctx.settings.bank_secret


def ensure_banks(
    conn: Connection, ctx: AppContext, profile: ProfileVersion, at: datetime | None = None
) -> dict:
    """Commit the current bank and, inside the commit-ahead window, the next one; reveal banks that ended."""
    at = at or now()
    rule = profile.question_bank
    current = period_index(rule, at)
    wanted = [current]
    next_start, _ = period_window(rule, current + 1)
    if (next_start - at).total_seconds() <= rule.commit_ahead_s:
        wanted.append(current + 1)
    committed, revealed = [], []
    for index in wanted:
        bid = bank_id(profile.profile_id, index)
        if conn.execute(select(question_banks.c.bank_id).where(question_banks.c.bank_id == bid)).first():
            continue
        seed = period_seed(_secret(ctx), profile.profile_id, index)
        starts, ends = period_window(rule, index)
        commitment = build_bank(bid, seed, rule).commitment()
        conn.execute(
            question_banks.insert().values(
                bank_id=bid,
                profile_id=profile.profile_id,
                period_index=index,
                starts_at=starts,
                ends_at=ends,
                commitment=commitment,
            )
        )
        audit.append(
            conn,
            "owner",
            "question_bank_committed",
            "question_bank",
            bid,
            {"commitment": commitment, "starts_at": starts.isoformat(), "ends_at": ends.isoformat()},
            public=True,
        )
        committed.append(bid)
    for row in conn.execute(
        select(question_banks).where(
            question_banks.c.profile_id == profile.profile_id,
            question_banks.c.ends_at <= at,
            question_banks.c.revealed_seed.is_(None),
        )
    ).all():
        seed = period_seed(_secret(ctx), profile.profile_id, row.period_index)
        conn.execute(
            update(question_banks)
            .where(question_banks.c.bank_id == row.bank_id)
            .values(revealed_seed=seed, revealed_at=now())
        )
        audit.append(
            conn, "owner", "question_bank_revealed", "question_bank", row.bank_id, {"seed": seed}, public=True
        )
        revealed.append(row.bank_id)
    return {"committed": committed, "revealed": revealed}


def bank_for_job(conn: Connection, ctx: AppContext, profile: ProfileVersion) -> dict:
    """The current period's bank as a worker receives it: its identifier and seed."""
    ensure_banks(conn, ctx, profile)
    index = period_index(profile.question_bank, now())
    return {
        "bank_id": bank_id(profile.profile_id, index),
        "seed": period_seed(_secret(ctx), profile.profile_id, index),
    }


def public_banks(conn: Connection, profile: ProfileVersion, limit: int = 12) -> dict:
    at = now()
    rows = conn.execute(
        select(question_banks)
        .where(question_banks.c.profile_id == profile.profile_id)
        .order_by(question_banks.c.period_index.desc())
        .limit(limit)
    ).all()
    rule = profile.question_bank
    return {
        "rule": rule.model_dump(),
        "banks": [
            {
                "bank_id": r.bank_id,
                "period_index": r.period_index,
                "starts_at": r.starts_at,
                "ends_at": r.ends_at,
                "commitment": r.commitment,
                "committed_at": r.committed_at,
                "status": "revealed"
                if r.revealed_seed
                else "current"
                if r.starts_at <= at < r.ends_at
                else "upcoming"
                if r.starts_at > at
                else "ended",
                "revealed_seed": r.revealed_seed,
            }
            for r in rows
        ],
    }
