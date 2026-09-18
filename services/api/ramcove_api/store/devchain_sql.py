"""PostgreSQL-backed store for the deterministic dev chain (SIMULATION ONLY)."""

from __future__ import annotations

from typing import Any

from ramcove_chain.types import Call, Event, Extrinsic
from sqlalchemy import Connection, func, select
from sqlalchemy.dialects.postgresql import insert

from .db import advisory_lock
from .schema import devchain_balances, devchain_blocks, devchain_registrations


def _call_to_json(c: Call) -> dict[str, Any]:
    return {
        "module": c.module,
        "function": c.function,
        "args": c.args,
        "inner": [_call_to_json(i) for i in c.inner],
    }


def _call_from_json(d: dict[str, Any]) -> Call:
    return Call(d["module"], d["function"], d["args"], tuple(_call_from_json(i) for i in d["inner"]))


def ext_to_json(e: Extrinsic) -> dict[str, Any]:
    return {
        "index": e.index,
        "signer": e.signer,
        "call": _call_to_json(e.call),
        "events": [
            {"module": v.module, "name": v.name, "attributes": v.attributes, "ext": v.extrinsic_index}
            for v in e.events
        ],
    }


class SqlDevChainStore:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def head_number(self) -> int:
        # Serialize block production: the controller, the API and scenarios can all produce blocks.
        advisory_lock(self.conn, "devchain-head")
        return int(
            self.conn.execute(select(func.coalesce(func.max(devchain_blocks.c.number), 0))).scalar() or 0
        )

    def append_block(self, number: int, block_hash: str, extrinsics: list[Extrinsic]) -> None:
        self.conn.execute(
            devchain_blocks.insert().values(
                number=number, hash=block_hash, extrinsics=[ext_to_json(e) for e in extrinsics]
            )
        )

    def extrinsics(self, number: int) -> list[Extrinsic]:
        row = self.conn.execute(select(devchain_blocks).where(devchain_blocks.c.number == number)).first()
        if not row:
            return []
        return [
            Extrinsic(
                number,
                row.hash,
                d["index"],
                d["signer"],
                _call_from_json(d["call"]),
                tuple(Event(v["module"], v["name"], v["attributes"], v["ext"]) for v in d["events"]),
            )
            for d in row.extrinsics
        ]

    def block_hash(self, number: int) -> str | None:
        return self.conn.execute(
            select(devchain_blocks.c.hash).where(devchain_blocks.c.number == number)
        ).scalar()

    def balance(self, account: str) -> int:
        return int(
            self.conn.execute(
                select(devchain_balances.c.rao).where(devchain_balances.c.account == account)
            ).scalar()
            or 0
        )

    def set_balance(self, account: str, rao: int) -> None:
        stmt = insert(devchain_balances).values(account=account, rao=rao)
        self.conn.execute(stmt.on_conflict_do_update(index_elements=["account"], set_={"rao": rao}))

    def registrations(self, netuid: int) -> dict[str, int]:
        rows = self.conn.execute(
            select(devchain_registrations).where(devchain_registrations.c.netuid == netuid)
        )
        return {r.hotkey: r.uid for r in rows}

    def register(self, netuid: int, hotkey: str) -> int:
        existing = self.registrations(netuid)
        if hotkey in existing:
            return existing[hotkey]
        used = set(existing.values())
        uid = next(i for i in range(256) if i not in used)  # lowest free UID: models UID reuse
        self.conn.execute(devchain_registrations.insert().values(netuid=netuid, hotkey=hotkey, uid=uid))
        return uid

    def deregister(self, netuid: int, hotkey: str) -> None:
        self.conn.execute(
            devchain_registrations.delete().where(
                (devchain_registrations.c.netuid == netuid) & (devchain_registrations.c.hotkey == hotkey)
            )
        )
