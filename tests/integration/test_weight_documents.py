"""The owner's signed weight result: issued by the controller, renewed every tempo, readable by anyone."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from ramcove_api.main import create_app
from ramcove_api.services import control
from ramcove_api.services.settlement import publish_weight_plan
from ramcove_api.services.weight_documents import ensure_weight_document, latest_signed
from ramcove_api.store.db import tx
from ramcove_api.store.schema import audit_events
from ramcove_protocol.weight_document import TEMPO_BLOCKS, check_document, signed_bytes
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


def test_the_controller_signs_a_result_any_validator_can_verify(ctx):
    control.tick(ctx)
    client = TestClient(
        create_app(ctx), base_url="https://testserver", headers={"x-ramcove-channel": "public"}
    )
    signed = client.get("/v1/weights/latest").json()
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
    r = client.get("/v1/weights/latest")
    assert r.status_code == 503 and r.json()["error"]["code"] == "no_weight_document"
