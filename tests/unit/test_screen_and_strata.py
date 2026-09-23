"""Screening's decisive failures and the stratification the quality bounds rest on (Sections 7.2, 8.6)."""

from __future__ import annotations

import collections
import json

import pytest
from ramcove_api.config import ROOT
from ramcove_evaluator import pipeline
from ramcove_evaluator.bank import build_bank
from ramcove_evaluator.target import StackParams
from ramcove_evaluator.taskgen import BANDS, offline_suite
from ramcove_protocol.rules import ProfileVersion


@pytest.fixture(scope="module")
def profile() -> ProfileVersion:
    return ProfileVersion.model_validate(
        json.loads((ROOT / "config/profiles/ramcove-p1@1.0.0.json").read_text())
    )


def test_the_long_context_items_are_spread_evenly_over_the_bands(profile):
    q = profile.question_bank
    items = offline_suite("seed", q.offline_long, q.offline_general)
    long_bands = collections.Counter(i.band for i in items if i.group != "general")
    assert set(long_bands) == set(range(len(BANDS)))
    # the per-band accuracy bound needs the same evidence in every band, including the widest contexts
    assert set(long_bands.values()) == {q.offline_long // len(BANDS)}
    positions = collections.Counter(i.group for i in items if i.group != "general")
    assert max(positions.values()) - min(positions.values()) <= 1


def test_a_stack_that_crashes_under_load_is_stopped_by_screening(profile):
    bank = build_bank("bank", "seed", profile.question_bank)
    champion = StackParams("champion")
    crashes = StackParams("crashes", crash_under_load=True, kv_factor=0.5)
    out = pipeline.screen(crashes, champion, profile, "seed", bank, {"capacity_milli_rps": 2000})
    assert out["decisive_failure"] == "errors", out
    assert "decisive limit 5%" in out["explanation"]


def test_a_stack_that_truncates_its_answers_is_stopped_by_screening(profile):
    bank = build_bank("bank", "seed", profile.question_bank)
    champion = StackParams("champion")
    truncates = StackParams("truncates", length_ratio_bp=2000)
    out = pipeline.screen(truncates, champion, profile, "seed", bank, {"capacity_milli_rps": 500})
    assert out["decisive_failure"] == "output_contract", out


def test_a_small_accuracy_gap_is_not_decisive_even_when_it_looks_large(profile):
    """200 items cannot separate small differences, so the gap must also be four standard errors wide."""
    bank = build_bank("bank", "seed", profile.question_bank)
    champion = StackParams("champion", base_accuracy_bp=9100)
    slightly_worse = StackParams("slightly-worse", base_accuracy_bp=8900)
    out = pipeline.screen(slightly_worse, champion, profile, "seed", bank, {"capacity_milli_rps": 500})
    assert out["decisive_failure"] is None, out
