"""Read-only checks against the public Finney RPC. Selected with: uv run pytest -m chain_readonly"""

import pytest
from ramcove_chain.network import FINNEY
from ramcove_chain.substrate_reader import SubstrateReader

pytestmark = pytest.mark.chain_readonly


@pytest.fixture(scope="module")
def reader():
    return SubstrateReader("wss://entrypoint-finney.opentensor.ai", FINNEY)


def test_genesis_identity_and_finality(reader):
    head = reader.finalized_head()
    assert head.number > 9_088_306


def test_parses_real_transfer_and_correlates_events(reader):
    ext = [e for e in reader.extrinsics(9_088_306) if e.index == 5][0]
    assert (ext.call.module, ext.call.function) == ("Balances", "transfer_keep_alive")
    names = [(e.module, e.name) for e in ext.events]
    assert ("System", "ExtrinsicSuccess") in names
    t = [e for e in ext.events if e.name == "Transfer"][0]
    assert t.attributes["amount"] == 295_647_070 == ext.call.args["value"]
    assert all(e.extrinsic_index == 5 for e in ext.events)
