"""Build a demo fixture artifact for a hotkey (demo mode only).

Fixtures carry labelled variants so the local demonstration can be repeated. Real artifacts get no such
help: exact and cosmetic duplicate detection applies to them unchanged.
"""

from __future__ import annotations

from room_miner.artifact import pack
from room_miner.fixtures import DEMO_VARIANTS, by_name, manifest_for, variant_patch
from room_protocol.canonical import sha256_hex
from room_protocol.preflight import normalize_patch
from sqlalchemy import select

from ..store.db import tx
from ..store.schema import artifacts
from .context import AppContext, ServiceError
from .queue import current_champion


def build(ctx: AppContext, hotkey: str, fixture_name: str) -> bytes:
    if not ctx.settings.demo_features:
        raise ServiceError("disabled", "demo fixtures are only available in demo mode", 403)
    try:
        fx = by_name(fixture_name)
    except KeyError as e:
        raise ServiceError("unknown_fixture", f"unknown fixture {fixture_name}", 404) from e
    with tx(ctx.engine) as conn:
        profile = ctx.profile(conn)
        champ = current_champion(conn, profile.profile_id)
        known: set[str] = set()
        for row in conn.execute(select(artifacts.c.sha256, artifacts.c.normalized_patch_sha256)):
            known.update({row.sha256, row.normalized_patch_sha256})
    manifest = manifest_for(fx, hotkey, profile.profile_id, profile.version, champ.version)
    for variant in range(DEMO_VARIANTS):
        patch = variant_patch(fx, variant)
        candidate = pack(manifest, patch)
        if sha256_hex(candidate) not in known and sha256_hex(normalize_patch(patch).encode()) not in known:
            return candidate
    raise ServiceError(
        "fixture_exhausted",
        f"every labelled variant of {fixture_name} has been submitted in this database; reset the demo data",
        409,
    )
