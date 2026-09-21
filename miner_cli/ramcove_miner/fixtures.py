"""Trusted demonstration fixtures (SIMULATION).

Each fixture is a small, harmless patch whose *normalized patch hash* identifies it to the simulated
isolation provider, plus the behaviour parameters of the simulated stack. The simulated provider only
evaluates artifacts whose hash appears in ``fixtures/trusted_fixtures.json``; everything else fails
closed because no real isolation backend is available in this build.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ramcove_evaluator.target import StackParams
from ramcove_protocol.canonical import sha256_hex
from ramcove_protocol.preflight import normalize_patch

ROOT = Path(__file__).resolve().parents[2]


def _patch(path: str, comment: str, line: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1,3 +1,4 @@\n"
        f" # vLLM KV cache module\n+# RamCove demo fixture: {comment}\n+{line}\n"
    )


FIXTURES = [
    {
        "name": "champion-v0-tuned",
        "role": "baseline",
        "title": "Tuned vLLM v0.29.0 baseline (champion version 0)",
        "params": StackParams("champion-v0-tuned"),
    },
    {
        "name": "kv8-conversation-retention",
        "role": "challenger",
        "lineage": "kv8-retention",
        "mechanism": "cache_storage",
        "title": "8-bit KV entries with conversation-aware retention",
        "method": "Stores KV entries in 8 bits with online scales and keeps idle conversation prefixes resident longer.",
        "patch": _patch("vllm/v1/core/kv_cache_manager.py", "kv8 retention", "KV8_RETENTION = True"),
        "params": StackParams(
            "kv8-conversation-retention",
            kv_factor=0.6,
            retention_bonus=0.25,
            accuracy_loss_bp={"position_early": 40},
        ),
    },
    {
        "name": "fragmentation-aware-allocator",
        "role": "challenger",
        "lineage": "frag-allocator",
        "mechanism": "allocation",
        "title": "Fragmentation-aware block allocation",
        "method": "Allocates KV blocks to reduce fragmentation so more tokens fit in the same budget.",
        "patch": _patch("vllm/v1/core/block_pool.py", "fragmentation aware", "FRAG_AWARE = True"),
        "params": StackParams("fragmentation-aware-allocator", usable_factor=1.8),
    },
    {
        "name": "native-paged-kv-kernel",
        "role": "challenger",
        "lineage": "native-paged-kv",
        "mechanism": "allocation",
        "title": "Native paged-KV packing kernel",
        "method": "A CUDA kernel packs KV blocks tightly so more tokens fit in the same budget. Native code, "
        "so a winner goes to a person before promotion.",
        "patch": (
            "diff --git a/vllm/v1/attention/ops/ramcove_paged_kv.cu b/vllm/v1/attention/ops/ramcove_paged_kv.cu\n"
            "--- a/vllm/v1/attention/ops/ramcove_paged_kv.cu\n+++ b/vllm/v1/attention/ops/ramcove_paged_kv.cu\n"
            "@@ -1,3 +1,4 @@\n // vLLM paged KV kernels\n+// RamCove demo fixture: native paged kv\n"
            "+#define RAMCOVE_PACKED_KV 1\n"
        ),
        "params": StackParams("native-paged-kv-kernel", usable_factor=1.8),
    },
    {
        "name": "evict-quarter",
        "role": "challenger",
        "lineage": "evict-quarter",
        "mechanism": "retention",
        "title": "Evict to a quarter of the cache",
        "method": "Keeps only the most attended quarter of cached tokens.",
        "patch": _patch("vllm/v1/core/sched/eviction.py", "evict quarter", "EVICT_FRACTION = 0.75"),
        "params": StackParams(
            "evict-quarter", kv_factor=0.25, accuracy_loss_bp={"position_early": 1900, "position_middle": 700}
        ),
    },
    {
        "name": "decode-kernel-speedup",
        "role": "challenger",
        "lineage": "decode-kernel",
        "mechanism": "mixed",
        "title": "Faster decode attention kernel",
        "method": "A faster decode attention kernel; no memory change.",
        "patch": _patch("vllm/v1/attention/backends/ramcove_fast.py", "decode kernel", "FAST_DECODE = True"),
        "params": StackParams("decode-kernel-speedup", compute_speedup=1.3),
    },
    {
        "name": "build-breaks",
        "role": "challenger",
        "lineage": "build-breaks",
        "mechanism": "allocation",
        "title": "Patch that does not build",
        "method": "Refactors the allocator but leaves a syntax error.",
        "patch": _patch("vllm/v1/core/kv_cache_utils.py", "broken build", "def broken(:"),
        "params": StackParams("build-breaks", screen_failure="build_failure"),
    },
    {
        "name": "quality-drift",
        "role": "challenger",
        "lineage": "quality-drift",
        "mechanism": "cache_storage",
        "title": "Aggressive 4-bit KV with small quality losses",
        "method": "4-bit KV entries; small per-generation accuracy losses that the fixed reference floor catches.",
        "patch": _patch("vllm/v1/attention/backends/ramcove_kv4.py", "kv4 drift", "KV4 = True"),
        "params": StackParams(
            "quality-drift", kv_factor=0.35, base_accuracy_bp=8800, accuracy_loss_bp={"position_late": 150}
        ),
    },
]


DEMO_VARIANTS = 6  # demo only: lets the local demonstration be re-run without weakening duplicate checks


def variant_patch(fixture: dict, variant: int) -> str:
    """Variant 0 is the fixture itself; later variants add one labelled line, so each is a distinct patch."""
    if variant == 0:
        return fixture["patch"]
    return fixture["patch"] + f"+RAMCOVE_DEMO_VARIANT = {variant}\n"


def by_name(name: str) -> dict:
    for f in FIXTURES:
        if f["name"] == name:
            return f
    raise KeyError(name)


def registry() -> dict[str, dict]:
    out = {}
    for f in FIXTURES:
        if f["role"] != "challenger":
            continue
        for variant in range(DEMO_VARIANTS):
            h = sha256_hex(normalize_patch(variant_patch(f, variant)).encode())
            out[h] = {
                "name": f["name"],
                "title": f["title"],
                "variant": variant,
                "params": asdict(f["params"]),
                "simulated": True,
            }
    return out


def write_registry() -> Path:
    path = ROOT / "fixtures" / "trusted_fixtures.json"
    path.parent.mkdir(exist_ok=True)
    baseline = asdict(by_name("champion-v0-tuned")["params"])
    path.write_text(
        json.dumps(
            {**registry(), "_baseline": {"name": "champion-v0-tuned", "params": baseline, "simulated": True}},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return path


def manifest_for(
    fixture: dict, hotkey: str, profile_id: str, profile_version: str, parent_version: int
) -> dict:
    return {
        "schema": "ramcove.manifest/1",
        "profile_id": profile_id,
        "profile_version": profile_version,
        "hotkey": hotkey,
        "lineage": fixture["lineage"],
        "parent_champion_version": parent_version,
        "method": fixture["method"],
        "mechanism": fixture["mechanism"],
        "license": "Apache-2.0",
        "third_party": [],
    }
