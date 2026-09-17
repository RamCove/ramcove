"""Free preflight: bounded parsing of a submission archive. Never executes candidate code.

Submission format ``room.artifact/1``: a gzip-compressed tar containing exactly
``manifest.json`` and ``patch.diff`` (a unified diff against the profile's pinned engine commit),
plus optional ``NOTICE`` / ``LICENSES/*`` text files.
"""

from __future__ import annotations

import fnmatch
import io
import json
import re
import tarfile
import zlib
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .canonical import sha256_hex
from .rules import ProfileVersion

ALLOWED_TOP = {"manifest.json", "patch.diff", "NOTICE"}
MANIFEST_MAX_BYTES = 64 * 1024


class ThirdParty(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    license: str
    url: str | None = None


class ArtifactManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    schema_: str = Field(alias="schema", pattern=r"^room\.manifest/1$")
    profile_id: str
    profile_version: str
    hotkey: str = Field(min_length=46, max_length=48)
    lineage: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    parent_champion_version: int = Field(ge=0)
    method: str = Field(min_length=10, max_length=2000)
    mechanism: str = Field(pattern=r"^(cache_storage|retention|allocation|admission|mixed)$")
    license: str
    third_party: list[ThirdParty] = Field(default_factory=list)


@dataclass
class PreflightResult:
    ok: bool
    artifact_sha256: str
    normalized_patch_sha256: str | None
    manifest: ArtifactManifest | None
    changed_paths: list[str] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    def fail(self, code: str, message: str) -> None:
        self.ok = False
        self.errors.append({"code": code, "message": message})


DIFF_PATH = re.compile(r"^(?:\+\+\+|---) (?:[ab]/)?(\S+)")


class _Capped(io.RawIOBase):
    """Decompress gzip with an absolute output cap to stop decompression bombs."""

    def __init__(self, data: bytes, cap: int) -> None:
        self._d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        self._src = memoryview(data)
        self._pos = 0
        self._buf = b""
        self._cap = cap
        self._out = 0

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:  # type: ignore[override]
        while not self._buf and (self._pos < len(self._src) or self._d.unconsumed_tail):
            chunk = self._d.unconsumed_tail or self._src[self._pos : self._pos + 65536].tobytes()
            if not self._d.unconsumed_tail:
                self._pos += 65536
            self._buf = self._d.decompress(chunk, 65536)
            self._out += len(self._buf)
            if self._out > self._cap:
                raise ValueError("decompressed size exceeds limit")
        n = min(len(b), len(self._buf))
        b[:n] = self._buf[:n]
        self._buf = self._buf[n:]
        return n


def normalize_patch(text: str) -> str:
    """Remove whitespace-only differences and diff metadata so cosmetic reformatting hashes equal."""
    out = []
    for line in text.splitlines():
        if line.startswith(("index ", "diff --git", "@@")):
            continue
        s = re.sub(r"\s+", " ", line).rstrip()
        if s in {"+", "-", ""}:
            continue
        out.append(s)
    return "\n".join(out)


def run_preflight(
    data: bytes,
    profile: ProfileVersion,
    known_hashes: set[str] | None = None,
    signature_ok: bool | None = None,
) -> PreflightResult:
    res = PreflightResult(True, sha256_hex(data), None, None)
    known = known_hashes or set()
    if len(data) > profile.archive_max_bytes:
        res.fail("archive_too_large", f"archive is {len(data)} bytes; limit {profile.archive_max_bytes}")
        return res
    if res.artifact_sha256 in known:
        res.fail("exact_duplicate", "identical bytes were already submitted or are the current champion")
        return res
    files: dict[str, bytes] = {}
    total = 0
    try:
        raw = io.BufferedReader(_Capped(data, profile.archive_max_unpacked_bytes))
        with tarfile.open(fileobj=raw, mode="r|") as tf:
            count = 0
            for m in tf:
                count += 1
                if count > profile.archive_max_entries:
                    res.fail("too_many_entries", "archive has too many entries")
                    return res
                name = m.name
                parts = name.split("/")
                if name.startswith("/") or "\\" in name or ".." in parts or ":" in parts[0] or "\x00" in name:
                    res.fail("unsafe_path", f"unsafe path {name!r}")
                    return res
                if m.issym() or m.islnk() or m.isdev() or m.isfifo() or m.ischr() or m.isblk():
                    res.fail("unsafe_entry", f"links and device files are not allowed ({name!r})")
                    return res
                if m.isdir():
                    continue
                if not m.isfile():
                    res.fail("unsafe_entry", f"unsupported entry type ({name!r})")
                    return res
                clean = name.removeprefix("./")
                top_ok = clean in ALLOWED_TOP or (clean.startswith("LICENSES/") and clean.count("/") == 1)
                if not top_ok:
                    res.fail("unexpected_file", f"{clean!r} is not part of the artifact format")
                    return res
                if clean in files:
                    res.fail("duplicate_entry", f"{clean!r} appears twice")
                    return res
                total += m.size
                if total > profile.archive_max_unpacked_bytes:
                    res.fail("unpacked_too_large", "unpacked size exceeds limit")
                    return res
                f = tf.extractfile(m)
                files[clean] = f.read(m.size + 1) if f else b""
    except (tarfile.TarError, ValueError, OSError, EOFError, zlib.error) as e:
        res.fail("bad_archive", f"archive could not be read safely: {e}")
        return res

    if "manifest.json" not in files or "patch.diff" not in files:
        res.fail("missing_files", "archive must contain manifest.json and patch.diff")
        return res
    if len(files["manifest.json"]) > MANIFEST_MAX_BYTES:
        res.fail("manifest_too_large", "manifest.json is too large")
        return res
    try:
        manifest = ArtifactManifest.model_validate(json.loads(files["manifest.json"]))
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as e:
        res.fail("bad_manifest", f"manifest.json is invalid: {str(e)[:300]}")
        return res
    res.manifest = manifest
    if manifest.profile_id != profile.profile_id or manifest.profile_version != profile.version:
        res.fail(
            "wrong_profile",
            f"manifest targets {manifest.profile_id}@{manifest.profile_version}; "
            f"open profile is {profile.profile_id}@{profile.version}",
        )
    if manifest.license not in profile.allowed_licenses:
        res.fail("license", f"license {manifest.license} is not in the allowed list")
    for tp in manifest.third_party:
        if tp.license not in profile.allowed_licenses:
            res.fail("license", f"third-party component {tp.name} uses {tp.license}, which is not allowed")
    if signature_ok is False:
        res.fail("bad_signature", "the hotkey signature over this artifact does not verify")
    try:
        patch = files["patch.diff"].decode("utf-8")
    except UnicodeDecodeError:
        res.fail("bad_patch", "patch.diff must be UTF-8 text")
        return res
    paths = sorted(
        {m.group(1) for line in patch.splitlines() if (m := DIFF_PATH.match(line))} - {"/dev/null"}
    )
    if not paths:
        res.fail("empty_patch", "patch.diff changes no files")
    res.changed_paths = paths
    for p in paths:
        if ".." in p.split("/") or p.startswith("/"):
            res.fail("unsafe_patch_path", f"patch path {p!r} is unsafe")
        elif any(fnmatch.fnmatch(p, g) for g in profile.engine.forbidden_paths):
            res.fail("forbidden_path", f"{p} is in a forbidden path")
        elif not any(fnmatch.fnmatch(p, g) for g in profile.engine.allowed_paths):
            res.fail("path_not_allowed", f"{p} is outside the allowed paths")
    norm = normalize_patch(patch)
    res.normalized_patch_sha256 = sha256_hex(norm.encode())
    if res.normalized_patch_sha256 in known:
        res.fail(
            "cosmetic_duplicate",
            "this patch matches an earlier submission after whitespace normalization; "
            "you may appeal with an explanation",
        )
    return res
