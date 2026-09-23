"""The profile is the contract, and its hash is recorded with every quote and comparison (Appendix A).

Everything the paper says is pinned must be inside the hashed object, or it could change under a
submission without changing the rule hash that submission was admitted under.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from ramcove_api.config import ROOT
from ramcove_protocol.rules import ProfileVersion

PROFILE = ROOT / "config/profiles/ramcove-p1@1.0.0.json"
ENGINE_ARGS = ROOT / "config/engine_args/ramcove-p1-h100sxm-qwen38-27b-fp8@1.0.0.json"


@pytest.fixture(scope="module")
def raw() -> dict:
    return json.loads(PROFILE.read_text())


def test_the_engine_arguments_in_use_are_the_ones_the_profile_hashes(raw):
    assert raw["engine"]["args_sha256"] == hashlib.sha256(ENGINE_ARGS.read_bytes()).hexdigest()


def test_serving_mode_and_evaluator_are_pinned(raw):
    p = ProfileVersion.model_validate(raw)
    assert (p.model.mode, p.model.decoding, p.model.max_model_len) == ("non-thinking", "greedy", 32768)
    assert p.hardware.tight_ceiling_share_bp == 2500
    assert p.evaluator.weights_version_key > 0


@pytest.mark.parametrize(
    "path, value",
    [
        (("model", "max_model_len"), 16384),
        (("engine", "cuda"), "12.9"),
        (("engine", "args_sha256"), "0" * 64),
        (("hardware", "driver"), "580.0"),
        (("hardware", "tight_ceiling_share_bp"), 2000),
        (("evaluator", "version"), "9.9.9"),
        (("latency", "stability_floor_bp"), 4000),
        (("deadlines", "beacon_min_delay_s"), 60),
    ],
)
def test_changing_any_pinned_value_changes_the_rule_hash(raw, path, value):
    before = ProfileVersion.model_validate(raw).rule_hash()
    changed = json.loads(json.dumps(raw))
    changed.setdefault(path[0], {})[path[1]] = value
    assert ProfileVersion.model_validate(changed).rule_hash() != before
