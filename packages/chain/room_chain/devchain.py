"""Deterministic development chain (SIMULATION). Never connects to a real network.

It produces extrinsics and events in the same normalized shapes as the real reader, including
failure modes (plain ``batch`` interruption, insufficient balance, wrong remark), so the payment
verifier is exercised end to end. Finality lags the head by ``finality_lag`` blocks.
State is kept in a pluggable store so the API, controller and tests share one durable chain.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from .network import DEVCHAIN
from .payment import blake2_256
from .types import Call, Event, Extrinsic, FinalizedHead

DEV_FEE_RAO = 166_251


class DevChainStore(Protocol):
    def head_number(self) -> int: ...
    def append_block(self, number: int, block_hash: str, extrinsics: list[Extrinsic]) -> None: ...
    def extrinsics(self, number: int) -> list[Extrinsic]: ...
    def block_hash(self, number: int) -> str | None: ...
    def balance(self, account: str) -> int: ...
    def set_balance(self, account: str, rao: int) -> None: ...
    def registrations(self, netuid: int) -> dict[str, int]: ...
    def register(self, netuid: int, hotkey: str) -> int: ...
    def deregister(self, netuid: int, hotkey: str) -> None: ...


def dev_block_hash(number: int) -> str:
    return "0x" + hashlib.sha256(f"room-devchain:{number}".encode()).hexdigest()


@dataclass
class MemoryStore:
    blocks: dict[int, tuple[str, list[Extrinsic]]]
    balances: dict[str, int]
    regs: dict[int, dict[str, int]]

    @classmethod
    def new(cls) -> MemoryStore:
        return cls({}, {}, {})

    def head_number(self) -> int:
        return max(self.blocks) if self.blocks else 0

    def append_block(self, number: int, block_hash: str, extrinsics: list[Extrinsic]) -> None:
        self.blocks[number] = (block_hash, extrinsics)

    def extrinsics(self, number: int) -> list[Extrinsic]:
        return list(self.blocks.get(number, ("", []))[1])

    def block_hash(self, number: int) -> str | None:
        b = self.blocks.get(number)
        return b[0] if b else None

    def balance(self, account: str) -> int:
        return self.balances.get(account, 0)

    def set_balance(self, account: str, rao: int) -> None:
        self.balances[account] = rao

    def registrations(self, netuid: int) -> dict[str, int]:
        return dict(self.regs.get(netuid, {}))

    def register(self, netuid: int, hotkey: str) -> int:
        m = self.regs.setdefault(netuid, {})
        if hotkey not in m:
            m[hotkey] = (max(m.values()) + 1) if m else 0
        return m[hotkey]

    def deregister(self, netuid: int, hotkey: str) -> None:
        self.regs.get(netuid, {}).pop(hotkey, None)


class DevChain:
    network = DEVCHAIN.name
    simulated = True

    def __init__(self, store: DevChainStore, finality_lag: int = 2) -> None:
        self.store = store
        self.finality_lag = finality_lag

    # --- reader interface ---
    def genesis_hash(self) -> str:
        return DEVCHAIN.genesis_hash

    def finalized_head(self) -> FinalizedHead:
        n = max(0, self.store.head_number() - self.finality_lag)
        return FinalizedHead(n, self.store.block_hash(n) or dev_block_hash(n))

    def block_hash(self, number: int) -> str | None:
        return self.store.block_hash(number)

    def extrinsics(self, block_number: int) -> list[Extrinsic]:
        return self.store.extrinsics(block_number)

    def hotkey_uid_map(self, netuid: int) -> tuple[int, dict[str, int]]:
        return self.finalized_head().number, self.store.registrations(netuid)

    # --- simulation controls ---
    def produce_block(self, extrinsic_specs: list[tuple[str, Call]] | None = None) -> int:
        number = self.store.head_number() + 1
        bh = dev_block_hash(number)
        exts: list[Extrinsic] = []
        for idx, (signer, call) in enumerate(extrinsic_specs or []):
            exts.append(Extrinsic(number, bh, idx, signer, call, tuple(self._apply(idx, signer, call))))
        self.store.append_block(number, bh, exts)
        return number

    def produce_blocks(self, count: int) -> int:
        n = 0
        for _ in range(count):
            n = self.produce_block()
        return n

    def _apply(self, idx: int, signer: str, call: Call) -> list[Event]:
        ev: list[Event] = []
        bal = self.store.balance(signer)
        if bal < DEV_FEE_RAO:
            return [Event("System", "ExtrinsicFailed", {"dispatch_error": "InsufficientBalance"}, idx)]
        self.store.set_balance(signer, bal - DEV_FEE_RAO)
        ev.append(
            Event("TransactionPayment", "TransactionFeePaid", {"who": signer, "actual_fee": DEV_FEE_RAO}, idx)
        )
        if call.module == "Utility" and call.function in {"batch", "batch_all"}:
            if call.function == "batch_all" and not self._all_dispatchable(signer, call.inner):
                # atomic: nothing is applied and the whole extrinsic fails
                return ev + [Event("System", "ExtrinsicFailed", {"dispatch_error": "BatchItemFailed"}, idx)]
            staged: list[Event] = []
            for i, inner in enumerate(call.inner):
                ok, inner_events = self._dispatch(signer, inner, idx)
                if not ok:  # only reachable for plain batch: earlier items stay applied
                    staged.append(Event("Utility", "BatchInterrupted", {"index": i, "error": "Failed"}, idx))
                    return ev + staged + [Event("System", "ExtrinsicSuccess", {}, idx)]
                staged.extend(inner_events)
                staged.append(Event("Utility", "ItemCompleted", {}, idx))
            return (
                ev
                + staged
                + [Event("Utility", "BatchCompleted", {}, idx), Event("System", "ExtrinsicSuccess", {}, idx)]
            )
        ok, inner_events = self._dispatch(signer, call, idx)
        if not ok:
            return ev + [Event("System", "ExtrinsicFailed", {"dispatch_error": "Failed"}, idx)]
        return ev + inner_events + [Event("System", "ExtrinsicSuccess", {}, idx)]

    def _all_dispatchable(self, signer: str, calls: tuple[Call, ...]) -> bool:
        spend = 0
        for c in calls:
            if (c.module, c.function) == ("Balances", "transfer_keep_alive"):
                spend += int(c.args["value"])
            elif (c.module, c.function) != ("System", "remark_with_event"):
                return False
        return self.store.balance(signer) - spend >= 500

    def _dispatch(self, signer: str, call: Call, idx: int) -> tuple[bool, list[Event]]:
        if (call.module, call.function) == ("Balances", "transfer_keep_alive"):
            dest, value = str(call.args["dest"]), int(call.args["value"])
            if self.store.balance(signer) - value < 500:
                return False, []
            self.store.set_balance(signer, self.store.balance(signer) - value)
            self.store.set_balance(dest, self.store.balance(dest) + value)
            return True, [Event("Balances", "Transfer", {"from": signer, "to": dest, "amount": value}, idx)]
        if (call.module, call.function) == ("System", "remark_with_event"):
            raw = call.args["remark"]
            data = (
                bytes.fromhex(raw[2:])
                if isinstance(raw, str) and raw.startswith("0x")
                else (raw if isinstance(raw, bytes) else str(raw).encode())
            )
            return True, [Event("System", "Remarked", {"sender": signer, "hash": blake2_256(data)}, idx)]
        return False, []


def payment_call(recipient: str, amount_rao: int, quote_id: str, plain_batch: bool = False) -> Call:
    remark = "0x" + (b"room:quote:" + quote_id.encode()).hex()
    return Call(
        "Utility",
        "batch" if plain_batch else "batch_all",
        {},
        (
            Call("Balances", "transfer_keep_alive", {"dest": recipient, "value": amount_rao}),
            Call("System", "remark_with_event", {"remark": remark}),
        ),
    )
