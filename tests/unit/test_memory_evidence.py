"""The memory check (ADR 0007): one noisy tighter-budget run must not decide a winner's fate."""

from dataclasses import replace

from ramcove_evaluator import pipeline
from ramcove_evaluator.capacity import CapacityResult
from ramcove_miner.fixtures import by_name

CAL = {"capacity_milli_rps": 500, "tight_capacity_milli_rps": 400}


def scripted(gains):
    """A stand-in for one tighter-budget reading per call, returning the given gains in order."""
    calls = []

    def reading(params, base, profile, seed, budget):
        g = gains[len(calls)]
        calls.append(seed)
        rps = base * (1 + g) if g > -1 else 0.0
        return CapacityResult(rps, 0 if rps else None, "ok", 3, ((0, True),), "reading-run0"), {}

    return reading, calls


def test_a_tighter_reading_that_misses_the_margin_gets_one_more(profile, monkeypatch):
    reading, calls = scripted([-1.0, 0.20])  # the first run failed on noise, the second clears the margin
    monkeypatch.setattr(pipeline, "_reading", reading)
    mem, _ = pipeline._memory_evidence(
        by_name("kv8-conversation-retention")["params"], 0.6, profile, "s", CAL
    )
    assert len(calls) == 2 and mem["tight_ok"] and mem["passed"]
    assert mem["tight_readings_ppm"][0] == -1_000_000 and mem["tight_budget_gain_ppm"] == 200_000


def test_a_clear_first_reading_needs_no_second(profile, monkeypatch):
    reading, calls = scripted([0.20])
    monkeypatch.setattr(pipeline, "_reading", reading)
    mem, _ = pipeline._memory_evidence(
        by_name("kv8-conversation-retention")["params"], 0.6, profile, "s", CAL
    )
    assert len(calls) == 1 and mem["passed"]


def test_two_misses_fail_and_a_compute_speedup_fails_on_accounting(profile, monkeypatch):
    reading, _ = scripted([0.02, 0.03])
    monkeypatch.setattr(pipeline, "_reading", reading)
    mem, _ = pipeline._memory_evidence(
        by_name("kv8-conversation-retention")["params"], 0.6, profile, "s", CAL
    )
    assert not mem["tight_ok"] and not mem["passed"]
    reading, _ = scripted([0.30])  # even a high tighter reading does not make a speedup a memory method
    monkeypatch.setattr(pipeline, "_reading", reading)
    speedup = replace(by_name("decode-kernel-speedup")["params"])
    mem, _ = pipeline._memory_evidence(speedup, 0.6, profile, "s", CAL)
    assert mem["tight_ok"] and not mem["accounting_ok"] and not mem["passed"]
