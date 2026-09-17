"""Real read-only Bittensor adapter (substrate-interface 1.8.1). No signing, no writes.

Integration status: parsing verified against finalized Finney block 9,088,306 extrinsic 5 by a
``chain_readonly`` test. Runtime event names checked against test-network metadata, spec 464.
"""

from __future__ import annotations

from typing import Any

from substrateinterface import SubstrateInterface

from .network import NetworkIdentity, require_identity
from .types import Call, Event, Extrinsic, FinalizedHead


def _args(call_args: list[dict[str, Any]]) -> dict[str, Any]:
    return {a["name"]: a["value"] for a in call_args}


def _to_call(d: dict[str, Any]) -> Call:
    args = _args(d.get("call_args", []))
    inner: tuple[Call, ...] = ()
    if d.get("call_module") == "Utility" and d.get("call_function") in {"batch", "batch_all", "force_batch"}:
        inner = tuple(_to_call(c) for c in args.get("calls", []))
    return Call(d.get("call_module", ""), d.get("call_function", ""), args, inner)


class SubstrateReader:
    def __init__(self, url: str, identity: NetworkIdentity, timeout_s: int = 30) -> None:
        self.network = identity.name
        self._identity = identity
        self._s = SubstrateInterface(url=url, ws_options={"timeout": timeout_s})
        require_identity(identity, self.genesis_hash())

    def genesis_hash(self) -> str:
        return str(self._s.get_block_hash(0))

    def finalized_head(self) -> FinalizedHead:
        h = self._s.get_chain_finalised_head()
        return FinalizedHead(int(self._s.get_block_number(h)), str(h))

    def block_hash(self, number: int) -> str | None:
        h = self._s.get_block_hash(number)
        return str(h) if h else None

    def extrinsics(self, block_number: int) -> list[Extrinsic]:
        bh = self._s.get_block_hash(block_number)
        block = self._s.get_block(block_hash=bh)
        events = []
        for rec in self._s.get_events(block_hash=bh):
            v = rec.value
            events.append(Event(v.get("module_id", ""), v.get("event_id", ""), v.get("attributes") or {},
                                v.get("extrinsic_idx") if v.get("phase") == "ApplyExtrinsic" else None))
        out = []
        for i, ex in enumerate(block["extrinsics"]):
            v = ex.value
            own = tuple(e for e in events if e.extrinsic_index == i)
            out.append(Extrinsic(block_number, str(bh), i, v.get("address"), _to_call(v["call"]), own))
        return out

    def hotkey_uid_map(self, netuid: int) -> tuple[int, dict[str, int]]:
        head = self.finalized_head()
        result: dict[str, int] = {}
        for key, value in self._s.query_map("SubtensorModule", "Keys", [netuid], block_hash=head.hash):
            result[str(value.value)] = int(key.value)
        return head.number, result

    def subnet_owner_hotkey(self, netuid: int) -> str:
        head = self.finalized_head()
        return str(self._s.query("SubtensorModule", "SubnetOwnerHotkey", [netuid], block_hash=head.hash).value)
