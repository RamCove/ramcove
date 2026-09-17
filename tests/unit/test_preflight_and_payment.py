import gzip
import io
import json
import tarfile

import pytest
from room_chain.devchain import DevChain, MemoryStore, payment_call
from room_chain.payment import Outcome, QuoteTerms, verify_payment
from room_chain.types import Call
from room_protocol.preflight import run_preflight

HOTKEY = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"


def manifest(profile, **over):
    m = {
        "schema": "room.manifest/1",
        "profile_id": profile.profile_id,
        "profile_version": profile.version,
        "hotkey": HOTKEY,
        "lineage": "kv-fragment-aware",
        "parent_champion_version": 0,
        "method": "Fragmentation-aware block allocator for the KV cache",
        "mechanism": "allocation",
        "license": "Apache-2.0",
        "third_party": [],
    }
    m.update(over)
    return json.dumps(m).encode()


PATCH = b"""diff --git a/vllm/v1/core/kv_cache_manager.py b/vllm/v1/core/kv_cache_manager.py
--- a/vllm/v1/core/kv_cache_manager.py
+++ b/vllm/v1/core/kv_cache_manager.py
@@ -1,3 +1,3 @@
-x = 1
+x = 2
"""


def make_tar(entries, gz=True):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data, kind in entries:
            ti = tarfile.TarInfo(name)
            if kind == "file":
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
            elif kind == "symlink":
                ti.type = tarfile.SYMTYPE
                ti.linkname = data.decode()
                tf.addfile(ti)
            elif kind == "hardlink":
                ti.type = tarfile.LNKTYPE
                ti.linkname = data.decode()
                tf.addfile(ti)
    raw = buf.getvalue()
    return gzip.compress(raw) if gz else raw


def test_valid_artifact_passes(profile):
    r = run_preflight(
        make_tar([("manifest.json", manifest(profile), "file"), ("patch.diff", PATCH, "file")]), profile
    )
    assert r.ok, r.errors
    assert r.changed_paths == ["vllm/v1/core/kv_cache_manager.py"]


@pytest.mark.parametrize("name", ["../evil", "/etc/passwd", "LICENSES/../../x", "a\\b"])
def test_path_traversal_rejected(profile, name):
    r = run_preflight(make_tar([(name, b"x", "file")]), profile)
    assert not r.ok and r.errors[0]["code"] in {"unsafe_path", "unexpected_file"}


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_links_rejected(profile, kind):
    r = run_preflight(make_tar([("manifest.json", b"/etc/passwd", kind)]), profile)
    assert not r.ok and r.errors[0]["code"] == "unsafe_entry"


def test_decompression_bomb_rejected_within_bounds(profile):
    bomb = make_tar([("patch.diff", b"0" * (profile.archive_max_unpacked_bytes + 1024), "file")])
    assert len(bomb) < profile.archive_max_bytes
    r = run_preflight(bomb, profile)
    assert not r.ok and r.errors[0]["code"] in {"bad_archive", "unpacked_too_large"}


def test_forbidden_and_disallowed_paths(profile):
    bad = PATCH.replace(b"vllm/v1/core/kv_cache_manager.py", b"vllm/entrypoints/api_server.py")
    r = run_preflight(
        make_tar([("manifest.json", manifest(profile), "file"), ("patch.diff", bad, "file")]), profile
    )
    assert not r.ok and any(e["code"] == "forbidden_path" for e in r.errors)


def test_license_and_wrong_profile(profile):
    m = manifest(profile, license="GPL-3.0", profile_version="0.9.0")
    r = run_preflight(make_tar([("manifest.json", m, "file"), ("patch.diff", PATCH, "file")]), profile)
    codes = {e["code"] for e in r.errors}
    assert {"license", "wrong_profile"} <= codes


def test_exact_and_cosmetic_duplicates(profile):
    art = make_tar([("manifest.json", manifest(profile), "file"), ("patch.diff", PATCH, "file")])
    first = run_preflight(art, profile)
    assert run_preflight(art, profile, {first.artifact_sha256}).errors[0]["code"] == "exact_duplicate"
    reformatted = PATCH.replace(b"+x = 2", b"+x   =   2  ")
    art2 = make_tar([("manifest.json", manifest(profile), "file"), ("patch.diff", reformatted, "file")])
    r = run_preflight(art2, profile, {first.normalized_patch_sha256})
    assert any(e["code"] == "cosmetic_duplicate" for e in r.errors)


def test_oversized_archive_rejected_before_parsing(profile):
    assert (
        run_preflight(b"\0" * (profile.archive_max_bytes + 1), profile).errors[0]["code"]
        == "archive_too_large"
    )


# ---------------- payments on the deterministic dev chain (SIMULATION) ----------------
PAYER, WALLET, OTHER = (
    "5Payer000000000000000000000000000000000000000000",
    "5Wallet00000000000000000000000000000000000000000",
    "5Other000000000000000000000000000000000000000000",
)


@pytest.fixture
def chain():
    c = DevChain(MemoryStore.new(), finality_lag=2)
    c.store.set_balance(PAYER, 10 * 10**9)
    c.store.set_balance(OTHER, 10 * 10**9)
    c.produce_blocks(3)
    return c


def terms(expires=100, amount=120_000_000, quote="q1", payer=PAYER):
    return QuoteTerms(quote, payer, WALLET, amount, expires, "room-devchain")


def pay(chain, signer=PAYER, amount=120_000_000, quote="q1", plain=False, call=None):
    n = chain.produce_block([(signer, call or payment_call(WALLET, amount, quote, plain_batch=plain))])
    chain.produce_blocks(2)
    return chain.extrinsics(n)[0]


def check(chain, ext, t, used=None, network="room-devchain"):
    return verify_payment(
        ext, t, chain.finalized_head(), chain.block_hash(ext.block_number), used or set(), network
    )


def test_valid_payment_verifies_and_overpayment_is_excess(chain):
    ext = pay(chain, amount=150_000_000)
    v = check(chain, ext, terms())
    assert v.outcome == Outcome.VERIFIED and v.excess_rao == 30_000_000


def test_not_finalized_is_deferred(chain):
    n = chain.produce_block([(PAYER, payment_call(WALLET, 120_000_000, "q1"))])
    v = check(chain, chain.extrinsics(n)[0], terms())
    assert v.outcome == Outcome.NOT_FINALIZED


@pytest.mark.parametrize(
    "case,expect",
    [
        ("wrong_payer", "signer is not the payer"),
        ("underpaid", "underpaid"),
        ("wrong_quote", "remark does not carry this quote"),
        ("plain_batch", "plain batch is refused"),
        ("reused", "already used"),
        ("wrong_network", "different network"),
    ],
)
def test_rejections(chain, case, expect):
    if case == "wrong_payer":
        ext = pay(chain, signer=OTHER)
        v = check(chain, ext, terms())
    elif case == "underpaid":
        v = check(chain, pay(chain, amount=100_000_000), terms())
    elif case == "wrong_quote":
        v = check(chain, pay(chain, quote="q2"), terms())
    elif case == "plain_batch":
        v = check(chain, pay(chain, plain=True), terms())
    elif case == "reused":
        ext = pay(chain)
        v = check(chain, ext, terms(), used={(ext.block_hash, ext.index)})
    else:
        v = check(chain, pay(chain), terms(), network="finney")
    assert v.outcome == Outcome.REJECTED and expect in v.reason


def test_failed_batch_all_is_rejected(chain):
    ext = pay(chain, amount=50 * 10**9)  # more than balance -> atomic failure
    v = check(chain, ext, terms(amount=50 * 10**9))
    assert v.outcome == Outcome.REJECTED and "did not succeed" in v.reason
    assert chain.store.balance(WALLET) == 0


def test_late_payment_is_refund_eligible(chain):
    ext = pay(chain)
    v = check(chain, ext, terms(expires=ext.block_number - 1))
    assert v.outcome == Outcome.LATE and v.refund_eligible


def test_forged_event_mismatch_rejected(chain):
    ext = pay(chain)
    forged_call = Call(
        "Utility",
        "batch_all",
        {},
        (ext.call.inner[0], Call("System", "remark_with_event", {"remark": "0x" + b"room:quote:q1".hex()})),
    )
    forged = type(ext)(
        ext.block_number,
        ext.block_hash,
        ext.index,
        ext.signer,
        forged_call,
        tuple(e for e in ext.events if e.name != "Remarked"),
    )
    assert check(chain, forged, terms()).outcome == Outcome.REJECTED


def test_non_canonical_block_rejected(chain):
    ext = pay(chain)
    v = verify_payment(ext, terms(), chain.finalized_head(), "0xdeadbeef", set(), "room-devchain")
    assert v.outcome == Outcome.REJECTED and "canonical" in v.reason
