"""The pooled accuracy gate (Section 8.2): a stack may not serve more by answering worse under load.

The simulated stacks answer the same whatever the load, so this gate cannot fire for a fixture. It is
tested directly instead, on the pooled logs a winner brings to it: its passing reading runs and its soak.
"""

from __future__ import annotations

import json

import pytest
from ramcove_api.config import ROOT
from ramcove_evaluator.loadgen import accuracy_gate, accuracy_under_load, run_once
from ramcove_evaluator.target import StackParams
from ramcove_protocol.rules import ProfileVersion


@pytest.fixture(scope="module")
def profile() -> ProfileVersion:
    return ProfileVersion.model_validate(
        json.loads((ROOT / "config/profiles/ramcove-p1@1.0.0.json").read_text())
    )


@pytest.fixture(scope="module")
def runs(profile) -> list:
    """A reading's passing run and an hour-long soak: an 8-minute run alone cannot bound anything."""
    reading, _ = run_once(StackParams("champion"), "pooled", 0.4, profile.latency)
    soak, _ = run_once(StackParams("champion"), "pooled:soak", 0.36, profile.latency, window_s=3600.0)
    return [reading, soak]


def test_an_answer_that_never_arrived_counts_as_wrong(runs):
    correct, offered = accuracy_under_load(runs)
    assert 0 < correct < offered == sum(len(r) for r in runs)


def test_the_gate_passes_against_a_champion_that_answered_the_same(profile, runs):
    correct, offered = accuracy_under_load(runs)
    # the champion's side comes from three 20-minute confirmation runs, so it is the larger sample
    ok, reasons, detail = accuracy_gate(
        runs, profile.quality, {"correct": correct * 4, "offered": offered * 4}
    )
    assert ok, (reasons, detail)
    assert abs(detail["difference_bp"]) < 100


def test_the_gate_fails_a_stack_that_answers_worse_under_load(profile, runs):
    correct, offered = accuracy_under_load(runs)
    champion = {"correct": min(offered, correct + offered // 20) * 4, "offered": offered * 4}
    ok, reasons, _ = accuracy_gate(runs, profile.quality, champion)
    assert ok is False
    assert any("accuracy under load" in r for r in reasons), reasons


def test_the_gate_does_not_run_when_the_champion_has_no_record(profile, runs):
    """A champion measured before this was recorded must not fail every challenger."""
    assert accuracy_gate(runs, profile.quality, None)[0] is None
    assert accuracy_gate(runs, profile.quality, {"correct": 0, "offered": 0})[0] is None
