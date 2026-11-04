"""set_weights on the dev chain: the checks the real chain makes before it accepts a validator's weights."""

from ramcove_chain.devchain import WEIGHTS_RATE_LIMIT_BLOCKS, DevChain, MemoryStore, weights_call


def chain_with(*hotkeys):
    chain = DevChain(MemoryStore.new())
    chain.produce_blocks(3)
    uids = {hk: chain.store.register(0, hk) for hk in hotkeys}
    return chain, uids


def submit(chain, signer, call):
    n = chain.produce_block([(signer, call)])
    ext = chain.extrinsics(n)[0]
    failed = next((e.attributes["dispatch_error"] for e in ext.events if e.name == "ExtrinsicFailed"), None)
    return n, failed


def test_a_registered_validator_sets_weights_without_a_fee():
    chain, uids = chain_with("5Owner", "5Val", "5King")
    n, failed = submit(chain, "5Val", weights_call(0, [uids["5Owner"], uids["5King"]], [52428, 13107], 100))
    assert failed is None
    block, args = chain.last_weights(0, "5Val")
    assert block == n and args["weights"] == [52428, 13107]
    assert chain.store.balance("5Val") == 0  # nothing was charged


def test_the_chain_refuses_bad_weight_vectors():
    chain, uids = chain_with("5Owner", "5Val")
    cases = {
        "HotKeyNotRegisteredInSubNet": ("5Stranger", weights_call(0, [0], [1], 100)),
        "WeightVecNotEqualSize": ("5Val", weights_call(0, [0, 1], [1], 100)),
        "DuplicateUids": ("5Val", weights_call(0, [0, 0], [1, 1], 100)),
        "UidVecContainInvalidOne": ("5Val", weights_call(0, [0, 99], [1, 1], 100)),
        "InvalidWeightValue": ("5Val", weights_call(0, [0], [70_000], 100)),
    }
    for expected, (signer, call) in cases.items():
        assert submit(chain, signer, call)[1] == expected
    assert chain.last_weights(0, "5Val") is None


def test_the_rate_limit_spaces_out_one_validator_s_weights():
    chain, uids = chain_with("5Owner", "5Val")
    call = weights_call(0, [uids["5Owner"]], [65_535], 100)
    first, _ = submit(chain, "5Val", call)
    assert submit(chain, "5Val", call)[1] == "SettingWeightsTooFast"
    chain.produce_blocks(WEIGHTS_RATE_LIMIT_BLOCKS)
    again, failed = submit(chain, "5Val", call)
    assert failed is None and chain.last_weights(0, "5Val")[0] == again > first
