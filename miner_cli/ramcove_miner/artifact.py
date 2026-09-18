"""Deterministic artifact packing (``ramcove.artifact/1``) and hotkey signing for the miner CLI."""

from __future__ import annotations

import gzip
import io
import json
import tarfile
from typing import Any

from ramcove_protocol.canonical import sha256_hex, signing_payload
from substrateinterface import Keypair


def pack(manifest: dict[str, Any], patch: str, notice: str | None = None) -> bytes:
    """Byte-for-byte reproducible tar.gz: fixed order, mtime 0, no owner names."""
    entries = [
        ("manifest.json", json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n"),
        ("patch.diff", patch.encode()),
    ]
    if notice:
        entries.append(("NOTICE", notice.encode()))
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tf:
        for name, data in entries:
            ti = tarfile.TarInfo(name)
            ti.size, ti.mtime, ti.mode, ti.uid, ti.gid, ti.uname, ti.gname = len(data), 0, 0o644, 0, 0, "", ""
            tf.addfile(ti, io.BytesIO(data))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def sign_artifact(keypair: Keypair, data: bytes, network: str, profile_id: str, profile_version: str) -> str:
    body = {
        "artifact_sha256": sha256_hex(data),
        "profile_id": profile_id,
        "profile_version": profile_version,
        "hotkey": keypair.ss58_address,
    }
    return "0x" + keypair.sign(signing_payload("artifact", network, body)).hex()
