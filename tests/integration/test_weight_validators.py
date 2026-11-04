"""The whole validator workflow in simulation: the owner evaluates and signs, every validator submits.

Neither validator here runs an evaluation. Both fetch the owner's signed result, check it, and set the
same weights on the dev chain, keyed to their own UID reads.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from ramcove_api.main import create_app
from ramcove_api.services import control
from ramcove_api.store.db import tx
from ramcove_validator.cli import HttpSource, SimulatedChain, SimulatedSubmitter, verify_sr25519
from ramcove_validator.core import PINNED_SIGNERS, State, run_cycle
from substrateinterface import Keypair

from .helpers import make_ctx

pytestmark = pytest.mark.db

VALIDATORS = ("//RamCoveDemoValidatorOperator", "//RamCoveDemoValidatorWeights")


@pytest.fixture
def ctx(tmp_path):
    return make_ctx(tmp_path)


def test_the_pinned_development_signer_is_the_services_own_key(ctx):
    assert PINNED_SIGNERS["ramcove-devchain"] == ctx.signer.address


def test_every_validator_submits_the_owner_s_result_without_evaluating(ctx):
    control.tick(ctx)
    pin = PINNED_SIGNERS["ramcove-devchain"]
    for uri in VALIDATORS:
        client = TestClient(create_app(ctx), base_url="https://testserver")
        kp = Keypair.create_from_uri(uri)
        out = run_cycle(
            HttpSource(client),
            SimulatedChain(client),
            SimulatedSubmitter(client, kp),
            State(),
            pin,
            verify_sr25519,
        )
        assert out.action == "submitted", out
    with tx(ctx.engine) as conn:
        chain = ctx.chain(conn)
        _, uids = chain.hotkey_uid_map(ctx.settings.netuid)
        rows = [
            chain.last_weights(ctx.settings.netuid, Keypair.create_from_uri(u).ss58_address)
            for u in VALIDATORS
        ]
    # only the baseline so far: both validators burn the whole miner allocation to the owner's UID
    assert all(r is not None and r[1]["dests"] == [uids[ctx.owner_hotkey]] for r in rows)
    assert rows[0][1]["weights"] == rows[1][1]["weights"] == [65_535]


def test_the_public_door_serves_the_result_but_not_the_simulation_routes(ctx):
    control.tick(ctx)
    public = TestClient(
        create_app(ctx), base_url="https://testserver", headers={"x-ramcove-channel": "public"}
    )
    assert public.get("/v1/weights/latest").status_code == 200
    assert public.get("/v1/weights/signer").json()["simulated_chain"] is True
    assert public.get("/v1/validator/chain").status_code == 403
    assert public.post("/v1/validator/weights", json={}).status_code == 403
