"""Canonical serialization and hashing for signed RamCove records.

Rules (versioned as ``ramcove.canonical/1``):
- JSON with sorted keys, no insignificant whitespace, UTF-8, ``ensure_ascii=False``.
- Floats are forbidden in signed records; money is integer rao, measurements are decimal strings.
- Every signed payload is prefixed with a domain separator so a signature for one record type
  or network can never be replayed as another.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

CANONICAL_VERSION = "ramcove.canonical/1"


class CanonicalError(ValueError):
    pass


def _check(value: Any, path: str = "$") -> None:
    if isinstance(value, float):
        raise CanonicalError(f"float not allowed in signed record at {path}; use integer or decimal string")
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise CanonicalError(f"non-string key at {path}")
            _check(v, f"{path}.{k}")
    elif isinstance(value, list | tuple):
        for i, v in enumerate(value):
            _check(v, f"{path}[{i}]")


def canonical_bytes(value: Any) -> bytes:
    _check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def record_hash(value: Any) -> str:
    return sha256_hex(canonical_bytes(value))


def signing_payload(record_type: str, network: str, value: Any) -> bytes:
    """Domain-separated bytes to sign: ``ramcove/v1|<record_type>|<network>|<canonical json>``."""
    if "|" in record_type or "|" in network:
        raise CanonicalError("record_type and network must not contain '|'")
    return b"ramcove/v1|" + record_type.encode() + b"|" + network.encode() + b"|" + canonical_bytes(value)
