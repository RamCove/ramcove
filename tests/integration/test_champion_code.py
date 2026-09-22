"""The baseline and each promoted champion's code are public, so miners can build on the champion."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile

import pytest
from fastapi.testclient import TestClient
from ramcove_api.main import create_app
from ramcove_miner import cli as miner_cli

from .helpers import bring_workers_online, drain, make_ctx, pay_and_admit, state, submit_fixture

pytestmark = pytest.mark.db

PUBLIC = {"x-ramcove-channel": "public"}


@pytest.fixture
def ctx(tmp_path):
    return make_ctx(tmp_path)


def promote_one(ctx) -> str:
    bring_workers_online(ctx)
    for variant in range(3):  # the simulated measurement is noisy; a miner would resubmit
        sub = submit_fixture(ctx, "miner-ada", "fragmentation-aware-allocator", variant=variant)
        pay_and_admit(ctx, sub["submission_id"], "miner-ada")
        drain(ctx)
        if state(ctx, sub["submission_id"]).state == "promoted":
            return sub["submission_id"]
    raise AssertionError("no promotion in three attempts")


def test_while_the_baseline_holds_the_crown_there_is_nothing_to_apply(ctx):
    public = TestClient(create_app(ctx), base_url="https://testserver", headers=PUBLIC)
    b = public.get("/v1/baseline").json()
    assert b["engine"]["commit"] == "98dff2a81d747d1dba01a47f939f48c3526d4206"
    assert b["current_champion_version"] == 0 and b["champion_stack"] == []
    assert b["engine_args"]["status"].startswith("provisional")
    r = public.get("/v1/champions/0/artifact")
    assert r.status_code == 404 and r.json()["error"]["code"] == "baseline"


def test_a_promoted_champions_code_is_public_and_the_miner_tool_writes_it(ctx, tmp_path, monkeypatch, capsys):
    promote_one(ctx)
    app = create_app(ctx)
    public = TestClient(app, base_url="https://testserver", headers=PUBLIC)
    b = public.get("/v1/baseline").json()
    assert b["current_champion_version"] == 1 and [c["version"] for c in b["champion_stack"]] == [1]
    r = public.get("/v1/champions/1/artifact")
    assert r.status_code == 200 and r.headers["content-type"] == "application/gzip"
    assert hashlib.sha256(r.content).hexdigest() == b["champion_stack"][0]["artifact_sha256"]
    with tarfile.open(fileobj=io.BytesIO(r.content), mode="r:gz") as tf:
        assert sorted(tf.getnames())[:2] == ["manifest.json", "patch.diff"]
    # the miner tool downloads the same code, checks its hash and writes the patch to apply
    monkeypatch.setattr(miner_cli, "_api", lambda base: TestClient(app))
    out = tmp_path / "champion"
    assert miner_cli.main(["champion-code", "--out", str(out)]) == 0
    stack = json.loads((out / "stack.json").read_text())
    assert [p["file"] for p in stack["patches"]] == ["01-champion-v1.diff"]
    assert (out / "01-champion-v1.diff").read_text().startswith("diff --git a/vllm/v1/core/block_pool.py")
    assert "baseline/fetch.sh vllm" in capsys.readouterr().out
