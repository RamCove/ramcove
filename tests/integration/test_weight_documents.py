"""The owner's signed weight result: issued by the controller, renewed every tempo, served only to validators."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from ramcove_api.main import create_app
from ramcove_api.services import control
from ramcove_api.services.settlement import publish_weight_plan
from ramcove_api.services.weight_documents import ensure_weight_document, latest_signed
from ramcove_api.store.db import tx
from ramcove_api.store.schema import audit_events
from ramcove_protocol.weight_document import TEMPO_BLOCKS, check_document, fetch_payload, signed_bytes
from ramcove_validator.cli import CliError, HttpSource
from sqlalchemy import func, select
from substrateinterface import Keypair

from .helpers import make_ctx

pytestmark = pytest.mark.db


@pytest.fixture
def ctx(tmp_path):
    return make_ctx(tmp_path)


def issued_events(conn) -> int:
    return conn.execute(
        select(func.count())
        .select_from(audit_events)
        .where(audit_events.c.action == "weight_document_issued")
    ).scalar()


VALIDATOR = Keypair.create_from_uri("//RamCoveDemoValidatorWeights")


def public_client(ctx) -> TestClient:
    return TestClient(create_app(ctx), base_url="https://testserver", headers={"x-ramcove-channel": "public"})


def test_the_controller_signs_a_result_any_validator_can_verify(ctx):
    control.tick(ctx)
    client = public_client(ctx)
    signed = HttpSource(client, VALIDATOR, ctx.settings.network).latest()
    signer = client.get("/v1/weights/signer").json()
    assert signer["address"] == signed["signer"] == ctx.signer.address
    doc = signed["document"]
    assert Keypair(ss58_address=signed["signer"]).verify(
        signed_bytes(doc), bytes.fromhex(signed["signature"][2:])
    )
    with tx(ctx.engine) as conn:
        chain = ctx.chain(conn)
        assert (
            check_document(
                doc,
                network=ctx.settings.network,
                genesis_hash=chain.genesis_hash(),
                netuid=ctx.settings.netuid,
                finalized_block=chain.finalized_head().number,
            )
            == []
        )
    # only the tuned baseline so far: no king, so the whole miner allocation goes to the owner's burn hotkey
    assert doc["shares"] == [{"hotkey": ctx.owner_hotkey, "share_bp": 10_000, "role": "burn"}]


def test_a_tampered_document_fails_the_signature_check(ctx):
    control.tick(ctx)
    with tx(ctx.engine) as conn:
        signed = latest_signed(conn, ctx)
    doc = dict(signed["document"])
    doc["shares"] = [{"hotkey": "5FakeKing", "share_bp": 10_000, "role": "king"}]
    assert not Keypair(ss58_address=signed["signer"]).verify(
        signed_bytes(doc), bytes.fromhex(signed["signature"][2:])
    )


def test_renewed_every_tempo_and_reissued_when_the_plan_changes(ctx):
    control.tick(ctx)
    with tx(ctx.engine) as conn:
        first = latest_signed(conn, ctx)["document"]
        assert ensure_weight_document(conn, ctx, ctx.profile(conn).profile_id) is None  # nothing due yet
        events = issued_events(conn)
        chain = ctx.chain(conn)
        chain.produce_blocks(first["valid_until_block"] - TEMPO_BLOCKS - chain.finalized_head().number + 3)
    control.tick(ctx, produce_block=False)
    with tx(ctx.engine) as conn:
        renewed = latest_signed(conn, ctx)["document"]
        assert renewed["issued_block"] > first["issued_block"] and renewed["plan_id"] == first["plan_id"]
        assert issued_events(conn) == events  # a routine renewal is not a new outcome
        publish_weight_plan(conn, ctx, ctx.profile(conn).profile_id)
    control.tick(ctx, produce_block=False)
    with tx(ctx.engine) as conn:
        assert latest_signed(conn, ctx)["document"]["plan_id"] != first["plan_id"]
        assert issued_events(conn) == events + 1


def test_no_result_yet_is_a_clear_error(ctx):
    client = TestClient(create_app(ctx), base_url="https://testserver")
    with pytest.raises(CliError, match="no_weight_document"):
        HttpSource(client, VALIDATOR, ctx.settings.network).latest()


def signed_headers(ctx, kp: Keypair, ts: int | None = None, path: str = "/v1/weights/latest") -> dict:
    ts = int(time.time()) if ts is None else ts
    sig = kp.sign(fetch_payload(ctx.settings.network, kp.ss58_address, ts, path))
    return {
        "x-ramcove-hotkey": kp.ss58_address,
        "x-ramcove-timestamp": str(ts),
        "x-ramcove-signature": "0x" + sig.hex(),
    }


def error_code(r) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def test_only_validators_can_read_the_result(ctx):
    control.tick(ctx)
    client = public_client(ctx)
    url = "/v1/weights/latest"
    # anyone else: no signature, a miner's hotkey, an unknown key, a stale or reused signature
    assert error_code(client.get(url)) == (401, "validator_signature_required")
    miner = Keypair.create_from_uri("//RamCoveDemoMinerAda")
    assert error_code(client.get(url, headers=signed_headers(ctx, miner))) == (403, "not_a_validator")
    stranger = Keypair.create_from_uri("//SomeoneWhoIsNotRegistered")
    assert error_code(client.get(url, headers=signed_headers(ctx, stranger))) == (403, "not_a_validator")
    stale = signed_headers(ctx, VALIDATOR, ts=int(time.time()) - 600)
    assert error_code(client.get(url, headers=stale)) == (401, "stale_request")
    other_path = signed_headers(ctx, VALIDATOR, path="/v1/weights/signer")
    assert error_code(client.get(url, headers=other_path)) == (401, "bad_signature")
    forged = signed_headers(ctx, VALIDATOR) | {"x-ramcove-hotkey": miner.ss58_address}
    assert error_code(client.get(url, headers=forged)) == (401, "bad_signature")
    # a validator: both the owner-operated one and one that only sets weights
    for uri in ("//RamCoveDemoValidatorOperator", "//RamCoveDemoValidatorWeights"):
        r = client.get(url, headers=signed_headers(ctx, Keypair.create_from_uri(uri)))
        assert r.status_code == 200 and r.json()["document"]["schema"] == "ramcove.weight_document/1"
    # the signer endpoint holds no scores and stays open
    assert client.get("/v1/weights/signer").status_code == 200


def test_the_public_site_shows_the_plan_status_but_not_the_weights(ctx):
    control.tick(ctx)
    plan = public_client(ctx).get("/v1/profile").json()["weight_plan"]
    assert plan is not None and "status" in plan
    assert "entries" not in plan and "kings" not in plan
