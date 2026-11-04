"""ramcove-validator's cycle: it submits only a result signed by the pinned owner key and fit for this chain."""

from __future__ import annotations

from ramcove_protocol.weight_document import TEMPO_BLOCKS, build_weight_document, signed_bytes
from ramcove_protocol.weights import U16_MAX, KingState, UidSnapshot, build_weight_plan
from ramcove_validator.cli import verify_sr25519
from ramcove_validator.core import RESUBMIT_BLOCKS, ChainView, State, run_cycle
from substrateinterface import Keypair

OWNER_KEY = Keypair.create_from_uri("//TestWeightSigner")
PIN = OWNER_KEY.ss58_address
GENESIS = "0x" + "00" * 31 + "01"


def signed_doc(kings=("5King1",), issued=1000, key=OWNER_KEY):
    snap = UidSnapshot(issued, 0, {hk: 10 + i for i, hk in enumerate(kings)} | {"5Owner": 0}, "5Owner")
    plan = build_weight_plan(
        [KingState("p1", i, 10 - i, hk, True) for i, hk in enumerate(kings, start=1)],
        {"p1": 10_000},
        snap,
        True,
    )
    doc = build_weight_document(
        plan.kings,
        netuid=0,
        network="ramcove-devchain",
        genesis_hash=GENESIS,
        burn_hotkey="5Owner",
        issued_block=issued,
        plan_id="wp_1",
        rule_hash="rh",
        champion_version=1,
        weights_version_key=100,
    )
    return {
        "document": doc,
        "signature": "0x" + key.sign(signed_bytes(doc)).hex(),
        "signer": key.ss58_address,
    }


class Source:
    def __init__(self, signed=None, error=None):
        self.signed, self.error = signed, error

    def latest(self):
        if self.error:
            raise self.error
        return self.signed


class Chain:
    def __init__(self, block=1100, uids=None, owner="5Owner", genesis=GENESIS):
        self.v = ChainView(
            "ramcove-devchain", genesis, 0, block, uids or {"5Owner": 0, "5King1": 7, "5Val": 9}, owner
        )

    def view(self):
        return self.v


class Submitter:
    hotkey = "5Val"

    def __init__(self, ok=True):
        self.calls, self.ok = [], ok

    def submit(self, uids, weights, version_key, document_hash):
        self.calls.append((uids, weights, version_key))
        return {"ok": self.ok, "block_number": 1101, "error": None if self.ok else "SettingWeightsTooFast"}


def cycle(source, chain=None, submitter=None, state=None, pin=PIN):
    submitter = submitter or Submitter()
    return run_cycle(source, chain or Chain(), submitter, state or State(), pin, verify_sr25519), submitter


def test_a_valid_result_is_submitted_with_the_validators_own_uids():
    out, sub = cycle(Source(signed_doc()))
    assert out.action == "submitted"
    assert sub.calls == [([7], [U16_MAX], 100)]  # the only king holds the whole allocation


def test_nothing_is_submitted_when_the_owner_is_unreachable():
    out, sub = cycle(Source(error=ConnectionError("down")))
    assert out.action == "unavailable" and sub.calls == []


def test_a_result_from_another_key_is_refused_even_if_correctly_signed():
    out, sub = cycle(Source(signed_doc(key=Keypair.create_from_uri("//SomeoneElse"))))
    assert out.action == "refused" and "pinned" in out.reason and sub.calls == []


def test_a_tampered_result_is_refused():
    signed = signed_doc()
    signed["document"]["shares"][0]["hotkey"] = "5Attacker"
    out, sub = cycle(Source(signed))
    assert out.action == "refused" and "signature" in out.reason and sub.calls == []


def test_an_expired_or_foreign_result_is_refused():
    expired, _ = cycle(Source(signed_doc()), Chain(block=1000 + 3 * TEMPO_BLOCKS))
    foreign, _ = cycle(Source(signed_doc()), Chain(genesis="0x" + "ab" * 32))
    assert expired.action == foreign.action == "refused"


def test_the_burn_must_go_to_the_subnet_owner():
    out, sub = cycle(Source(signed_doc()), Chain(owner="5SomeoneElse"))
    assert out.action == "refused" and "owner" in out.reason and sub.calls == []


def test_an_unregistered_validator_does_not_submit():
    out, sub = cycle(Source(signed_doc()), Chain(uids={"5Owner": 0, "5King1": 7}))
    assert out.action == "refused" and sub.calls == []


def test_the_same_result_is_resubmitted_only_once_a_tempo(tmp_path):
    state = State(tmp_path / "state.json")
    first, _ = cycle(Source(signed_doc()), state=state)
    again, sub = cycle(Source(signed_doc()), Chain(block=1101 + RESUBMIT_BLOCKS - 1), state=state)
    later, sub2 = cycle(Source(signed_doc(issued=1101)), Chain(block=1101 + RESUBMIT_BLOCKS), state=state)
    assert (first.action, again.action, later.action) == ("submitted", "up_to_date", "submitted")
    assert sub.calls == [] and len(sub2.calls) == 1
    assert State.load(tmp_path / "state.json").block == 1101


def test_a_chain_refusal_is_reported_and_not_recorded():
    state = State()
    out, _ = cycle(Source(signed_doc()), submitter=Submitter(ok=False), state=state)
    assert out.action == "failed" and state.document_hash is None
