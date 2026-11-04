"""The signed weight result the owner publishes and every validator checks and submits."""

import pytest
from ramcove_protocol.weight_document import (
    SCHEMA,
    TEMPO_BLOCKS,
    VALID_TEMPOS,
    WeightDocumentError,
    build_weight_document,
    chain_weights,
    check_document,
    document_hash,
    fetch_payload,
    needs_reissue,
    signed_bytes,
)
from ramcove_protocol.weights import U16_MAX, KingState, UidSnapshot, build_weight_plan

GENESIS = "0x" + "00" * 31 + "01"


def plan(*hotkeys):
    snap = UidSnapshot(500, 0, {hk: 10 + i for i, hk in enumerate(hotkeys)} | {"5Owner": 0}, "5Owner")
    kings = [KingState("p1", i, 10 - i, hk, True) for i, hk in enumerate(hotkeys, start=1)]
    return build_weight_plan(kings, {"p1": 10_000}, snap, no_winner_mechanism_verified=True)


def doc_for(p, issued=1000, plan_id="wp_1"):
    return build_weight_document(
        p.kings,
        netuid=p.netuid,
        network="ramcove-devchain",
        genesis_hash=GENESIS,
        burn_hotkey="5Owner",
        issued_block=issued,
        plan_id=plan_id,
        rule_hash="rh",
        champion_version=1,
        weights_version_key=100,
    )


def check(doc, block=1100):
    return check_document(
        doc, network="ramcove-devchain", genesis_hash=GENESIS, netuid=0, finalized_block=block
    )


def test_one_king_gets_the_whole_allocation():
    doc = doc_for(plan("5King1"))
    assert doc["schema"] == SCHEMA
    assert doc["shares"] == [{"hotkey": "5King1", "share_bp": 10_000, "role": "king"}]
    assert doc["burn_hotkey"] == "5Owner"  # still named: an unregistered king's share goes there
    assert doc["valid_until_block"] == 1000 + VALID_TEMPOS * TEMPO_BLOCKS
    assert [k["slot"] for k in doc["kings"]] == [1, 2, 3, 4, 5]
    assert check(doc) == []


def test_five_kings_share_everything_and_nothing_burns():
    doc = doc_for(plan("5A", "5B", "5C", "5D", "5E"))
    assert {r["hotkey"]: r["share_bp"] for r in doc["shares"]} == {
        hk: 2000 for hk in ("5A", "5B", "5C", "5D", "5E")
    }
    assert all(r["role"] == "king" for r in doc["shares"])


def test_the_signed_bytes_are_domain_separated_and_stable():
    doc = doc_for(plan("5King1"))
    assert signed_bytes(doc).startswith(b"ramcove/v1|weight_document|ramcove-devchain|")
    assert signed_bytes(doc) == signed_bytes(dict(reversed(list(doc.items()))))
    assert document_hash(doc) == document_hash(dict(doc))


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"network": "finney"}, "network"),
        ({"genesis_hash": "0xbad"}, "genesis"),
        ({"netuid": 7}, "netuid"),
        ({"valid_until_block": 1050}, "valid for blocks"),
        ({"issued_block": 1200}, "valid for blocks"),
    ],
)
def test_a_validator_refuses_a_document_for_another_chain_or_window(change, problem):
    doc = doc_for(plan("5King1")) | change
    assert any(problem in p for p in check(doc))


def test_tampered_shares_are_refused():
    doc = doc_for(plan("5King1"))
    doc["shares"][0]["share_bp"] = 9000
    assert any("add up" in p for p in check(doc))
    assert check(doc_for(plan("5King1")) | {"schema": "other/1"}) == ["unknown schema 'other/1'"]


def test_reissue_when_missing_changed_or_near_expiry():
    doc = doc_for(plan("5King1"))
    assert needs_reissue(None, "wp_1", 1000)
    assert needs_reissue(doc, "wp_2", 1000)  # a new champion changed the plan
    assert not needs_reissue(doc, "wp_1", doc["valid_until_block"] - TEMPO_BLOCKS)
    assert needs_reissue(doc, "wp_1", doc["valid_until_block"] - TEMPO_BLOCKS + 1)


def test_chain_weights_use_the_validators_own_uid_map():
    doc = doc_for(plan("5King1", "5King2"))
    uids, weights, notes = chain_weights(doc, {"5Owner": 0, "5King1": 7, "5King2": 3})
    assert dict(zip(uids, weights, strict=True)) == {
        3: 2000 * U16_MAX // 10_000,
        7: 8000 * U16_MAX // 10_000,
    }
    assert notes == []


def test_an_unregistered_king_s_share_goes_to_the_burn_hotkey():
    doc = doc_for(plan("5King1", "5King2"))
    uids, weights, notes = chain_weights(doc, {"5Owner": 0, "5King1": 7})
    assert dict(zip(uids, weights, strict=True)) == {0: 2000 * U16_MAX // 10_000, 7: 8000 * U16_MAX // 10_000}
    assert notes and "5King2" in notes[0]


def test_no_submission_without_a_registered_burn_hotkey():
    with pytest.raises(WeightDocumentError):
        chain_weights(doc_for(plan("5King1")), {"5King1": 7})


def test_a_validator_s_read_is_signed_for_one_network_path_hotkey_and_time():
    a = fetch_payload("ramcove-devchain", "5Validator", 1000)
    assert a.startswith(b"ramcove/v1|weight_fetch|ramcove-devchain|")
    others = [
        fetch_payload("finney", "5Validator", 1000),
        fetch_payload("ramcove-devchain", "5Other", 1000),
        fetch_payload("ramcove-devchain", "5Validator", 1001),
        fetch_payload("ramcove-devchain", "5Validator", 1000, "/v1/weights/signer"),
    ]
    assert all(a != o for o in others)
