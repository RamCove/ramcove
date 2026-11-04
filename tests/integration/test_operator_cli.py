"""The operator and reviewers run the network from ramcove-operator, each signing in with their own key.

The command line drives the real API in-process, so the same role checks and audit trail apply as for any
other client.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from ramcove_api import operator_cli
from ramcove_api.main import create_app
from ramcove_api.services import seed

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


@pytest.fixture
def ctx(tmp_path):
    return make_ctx(tmp_path)


@pytest.fixture
def run(ctx, monkeypatch, capsys):
    app = create_app(ctx)
    monkeypatch.setattr(operator_cli, "_api", lambda base: TestClient(app))

    def _run(identity: str, *args: str) -> tuple[int, str, str]:
        uri = next(d.uri for d in seed.DEMO_IDENTITIES if d.key == identity)
        code = operator_cli.main(["--key-uri", uri, *args])
        out = capsys.readouterr()
        return code, out.out, out.err

    return _run


def test_the_operator_sees_the_console_and_verifies_the_audit_chain(run):
    code, out, _ = run("operator", "console")
    assert code == 0 and out.startswith("intake     open")
    code, out, _ = run("operator", "audit-verify")
    assert code == 0 and '"ok": true' in out


def test_the_operator_pauses_intake_and_manages_incidents(run):
    assert run("operator", "intake", "pause", "--reason", "maintenance window")[0] == 0
    assert "intake     PAUSED" in run("operator", "console")[1]
    assert run("operator", "intake", "resume", "--reason", "maintenance done")[0] == 0
    code, out, _ = run(
        "operator",
        "incident",
        "open",
        "--severity",
        "minor",
        "--title",
        "Slow queue",
        "--summary",
        "Workers restart.",
    )
    assert code == 0
    incident = out.split('"id": "')[1].split('"')[0]
    assert f"incident   {incident}" in run("operator", "console")[1]
    assert run("operator", "incident", "resolve", incident)[0] == 0
    assert incident not in run("operator", "console")[1]


def test_roles_still_decide_what_each_key_may_do(run):
    code, _, err = run("miner-bao", "console")
    assert code == 1 and "forbidden" in err
    code, _, err = run("operator", "intake", "pause", "--reason", "x")
    assert code == 1  # the reason is too short; nothing changed
    assert "intake     open" in run("operator", "console")[1]


def test_a_reviewer_decides_a_promotion_from_the_command_line(ctx, run):
    bring_workers_online(ctx)
    # a native kernel is flagged for a person; the simulated evaluation is noisy, so resubmit as a miner would
    sub_id, outcomes = None, []
    for attempt in range(ATTEMPTS):
        bring_workers_online(ctx)  # readiness expires in 120 s, and resubmitting takes longer than that
        sub = submit_fixture(ctx, "miner-ada", "native-paged-kv-kernel", variant=attempt)
        admit_submission(ctx, sub["submission_id"], "miner-ada")
        drain(ctx)
        st = state(ctx, sub["submission_id"])
        if st.state == "in_review":
            sub_id = sub["submission_id"]
            break
        outcomes.append(st.outcome_code)
    if not sub_id and only_measurement_noise(outcomes):
        pytest.skip(f"this worker's champion score rejected every attempt: {outcomes}")
    assert sub_id, f"no submission reached review in {ATTEMPTS} attempts: {outcomes}"
    code, out, _ = run("reviewer-1", "reviews")
    assert code == 0 and sub_id in out and "flagged: native_review" in out
    review_id = next(line.split()[0] for line in out.splitlines() if sub_id in line)
    # a rejection must cite a failed criterion
    code, _, err = run(
        "reviewer-1", "review", review_id, "reject", "--reasons", "not good enough for this profile"
    )
    assert code == 1 and "reason_required" in err
    code, _, err = run("reviewer-1", "review", review_id, "approve", "--failed", "made-up")
    assert code == 1 and "unknown criteria" in err
    code, out, _ = run("reviewer-1", "review", review_id, "approve", "--reasons", "all criteria checked")
    assert code == 0, out
    assert state(ctx, sub_id).state in {"ready_for_promotion", "promoted"}
