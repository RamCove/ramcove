"""Normalized chain data, independent of any SDK. Adapters convert into these shapes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class Call:
    module: str
    function: str
    args: dict[str, Any]
    inner: tuple[Call, ...] = ()


@dataclass(frozen=True)
class Event:
    module: str
    name: str
    attributes: dict[str, Any]
    extrinsic_index: int | None  # None for non-ApplyExtrinsic phases


@dataclass(frozen=True)
class Extrinsic:
    block_number: int
    block_hash: str
    index: int
    signer: str | None
    call: Call
    events: tuple[Event, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class FinalizedHead:
    number: int
    hash: str


class ChainReader(Protocol):
    network: str

    def genesis_hash(self) -> str: ...
    def finalized_head(self) -> FinalizedHead: ...
    def block_hash(self, number: int) -> str | None: ...
    def extrinsics(self, block_number: int) -> list[Extrinsic]: ...
    def hotkey_uid_map(self, netuid: int) -> tuple[int, dict[str, int]]: ...
