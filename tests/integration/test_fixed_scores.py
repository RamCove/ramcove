"""Which number was measured where.

Capacity is measured per worker, so the champion's published capacity and a challenger's gain rest on
different baselines. The public views must say so, or the two cannot be reconciled by a reader.
"""

from __future__ import annotations

import pytest
from ramcove_api.services import public
from ramcove_api.store.db import tx
from ramcove_api.store.schema import comparisons
from sqlalchemy import select

from .helpers import (
    ATTEMPTS,
    bring_workers_online,
    drain,
    make_ctx,
    pay_and_admit,
    state,
    submit_fixture,
)

pytestmark = pytest.mark.db


@pytest.fixture
def ctx(tmp_path):
    return make_ctx(tmp_path)


def test_a_champion_says_which_score_its_gain_was_measured_against(ctx):
    for variant in range(ATTEMPTS):
        bring_workers_online(ctx)
        sub = submit_fixture(ctx, "miner-ada", "fragmentation-aware-allocator", variant=variant)
        pay_and_admit(ctx, sub["submission_id"], "miner-ada")
        drain(ctx)
        if state(ctx, sub["submission_id"]).state == "promoted":
            break
    else:
        pytest.skip(f"no promotion in {ATTEMPTS} attempts; the simulated measurement is noisy")

    d = public.dashboard(ctx)
    champ = d["champion"]
    with tx(ctx.engine) as conn:
        cmp_row = conn.execute(
            select(comparisons).where(comparisons.c.submission_id == sub["submission_id"])
        ).first()
    # the gain is the reading over the fixed score of the worker that judged it, not over the number shown
    assert champ["measured_against_milli_rps"] == cmp_row.champion_milli_rps
    assert champ["measured_on_worker"] == cmp_row.worker
    assert champ["reading_milli_rps"] == cmp_row.challenger_milli_rps
    gain = champ["reading_milli_rps"] / champ["measured_against_milli_rps"] - 1
    assert abs(gain * 1e6 - champ["bound_gain_ppm"]) <= 1e6 * 0.005


def test_every_worker_publishes_its_own_fixed_score(ctx):
    bring_workers_online(ctx)
    sub = submit_fixture(ctx, "miner-bao", "kv8-conversation-retention")
    pay_and_admit(ctx, sub["submission_id"], "miner-bao")
    drain(ctx)  # calibrates both workers on the way to screening the submission

    scores = public.dashboard(ctx)["fixed_scores"]
    assert {s["worker"] for s in scores} >= {"w-op-1", "w-op-2"}
    for s in scores:
        assert s["fixed_score_milli_rps"] > 0
        assert s["tight_fixed_score_milli_rps"] > 0
        assert s["current"] is True
    assert public.status_page(ctx)["fixed_scores"] == scores
