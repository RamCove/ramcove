"""The trusted-fixture registry is generated, so it can fall behind the code that uses it.

A simulated worker refuses any artifact whose hash is not in the registry, and intake then reports "no
evaluation worker is safe and ready" — which looks like a capacity problem and is not one. A journey test
resubmits up to ATTEMPTS times, each with a new variant, so the registry must hold at least that many.
"""

from __future__ import annotations

import json

from ramcove_api.config import ROOT
from ramcove_miner.fixtures import (
    DEMO_VARIANTS,
    FIXTURES,
    normalize_patch,
    registry,
    sha256_hex,
    variant_patch,
)


def test_the_registry_on_disk_matches_the_fixtures_in_code():
    on_disk = json.loads((ROOT / "fixtures" / "trusted_fixtures.json").read_text())
    generated = registry()
    assert {k for k in on_disk if not k.startswith("_")} == set(generated), (
        "fixtures/trusted_fixtures.json is stale: run "
        "`uv run python -c 'from ramcove_miner.fixtures import write_registry; write_registry()'`"
    )


def test_every_variant_a_test_can_submit_is_trusted():
    from tests.integration.helpers import ATTEMPTS

    assert DEMO_VARIANTS >= ATTEMPTS, (
        "raise DEMO_VARIANTS and regenerate the registry before raising ATTEMPTS"
    )
    on_disk = json.loads((ROOT / "fixtures" / "trusted_fixtures.json").read_text())
    for fx in FIXTURES:
        if fx["role"] != "challenger":
            continue
        for variant in range(ATTEMPTS):
            h = sha256_hex(normalize_patch(variant_patch(fx, variant)).encode())
            assert h in on_disk, f"{fx['name']} variant {variant} is not in the registry"
