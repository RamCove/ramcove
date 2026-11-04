"""Each promoted champion's code is public, so miners can build on it. The engine itself is not hosted."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile

import pytest
from fastapi.testclient import TestClient
from ramcove_api.main import create_app
from ramcove_miner import cli as miner_cli

from .helpers import (
    ATTEMPTS,
    admit_submission,
    bring_workers_online,
    drain,
    make_ctx,
    only_measurement_noise,
    state,
    submit_fixture,
)

pytestmark = pytest.mark.db

PUBLIC = {"x-ramcove-channel": "public"}


@pytest.fixture
def ctx(tmp_path):
    return make_ctx(tmp_path)


def promote_one(ctx) -> str:
    bring_workers_online(ctx)
    outcomes: list[str | None] = []
    for variant in range(ATTEMPTS):  # the simulated measurement is noisy; a miner would resubmit
        bring_workers_online(ctx)  # readiness expires in 120 s, and resubmitting takes longer than that
        sub = submit_fixture(ctx, "miner-ada", "fragmentation-aware-allocator", variant=variant)
        admit_submission(ctx, sub["submission_id"], "miner-ada")
        drain(ctx)
        st = state(ctx, sub["submission_id"])
        if st.state == "promoted":
            return sub["submission_id"]
        outcomes.append(st.outcome_code)
    if only_measurement_noise(outcomes):
        pytest.skip(f"this worker's champion score rejected every attempt: {outcomes}")
    raise AssertionError(f"no promotion in {ATTEMPTS} attempts: {outcomes}")


def test_while_the_baseline_holds_the_crown_there_is_nothing_to_apply(ctx):
    public = TestClient(create_app(ctx), base_url="https://testserver", headers=PUBLIC)
    b = public.get("/v1/champion-code").json()
    assert b["engine"]["commit"] == "98dff2a81d747d1dba01a47f939f48c3526d4206"
    assert b["current_champion_version"] == 0 and b["patches"] == []
    assert b["engine_args"]["status"].startswith("provisional")
    assert public.get("/v1/baseline").status_code == 404  # RamCove does not host the engine
    r = public.get("/v1/champions/0/artifact")
    assert r.status_code == 404 and r.json()["error"]["code"] == "baseline"


def test_a_promoted_champions_code_is_public_and_the_miner_tool_writes_it(ctx, tmp_path, monkeypatch, capsys):
    promote_one(ctx)
    app = create_app(ctx)
    public = TestClient(app, base_url="https://testserver", headers=PUBLIC)
    b = public.get("/v1/champion-code").json()
    assert b["current_champion_version"] == 1 and [c["version"] for c in b["patches"]] == [1]
    r = public.get("/v1/champions/1/artifact")
    assert r.status_code == 200 and r.headers["content-type"] == "application/gzip"
    assert hashlib.sha256(r.content).hexdigest() == b["patches"][0]["artifact_sha256"]
    with tarfile.open(fileobj=io.BytesIO(r.content), mode="r:gz") as tf:
        assert sorted(tf.getnames())[:2] == ["manifest.json", "patch.diff"]
    # the miner tool downloads the same code, checks its hash and writes the patch to apply
    monkeypatch.setattr(miner_cli, "_api", lambda base: TestClient(app))
    out = tmp_path / "champion"
    assert miner_cli.main(["champion-code", "--out", str(out)]) == 0
    stack = json.loads((out / "stack.json").read_text())
    assert [p["file"] for p in stack["patches"]] == ["01-champion-v1.diff"]
    assert (out / "01-champion-v1.diff").read_text().startswith("diff --git a/vllm/v1/core/block_pool.py")
    assert "apply them in order to vllm-project/vllm at 98dff2a8" in capsys.readouterr().out
