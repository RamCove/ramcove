import gzip
import io
import json
import tarfile

import pytest
from ramcove_protocol.preflight import run_preflight

HOTKEY = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"


def manifest(profile, **over):
    m = {
        "schema": "ramcove.manifest/1",
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
