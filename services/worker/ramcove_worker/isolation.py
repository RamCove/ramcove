"""Isolation providers. Miner code is hostile; the worker process itself never imports or executes it.

``SimulatedTrustedProvider`` (SIMULATION): evaluates only trusted repository fixtures identified by
normalized patch hash, using the simulated serving model. It declares ``untrusted_code_isolation: false``,
so the controller never assigns it an untrusted artifact and paid quotes for such artifacts are refused.

``VfioVmProvider``: the intended boundary - one hardware-virtualized VM per candidate with the whole GPU
passed through by VFIO, no network interface, a vsock channel only to the trusted host-side measurement
agent, read-only verified image, destroy + GPU reset between jobs. This build implements its readiness
probes and launch specification; it has NOT been run on H100 SXM hardware and fails closed when any
requirement is missing.
"""

from __future__ import annotations

import gzip
import io
import os
import shutil
import subprocess  # noqa: S404 - fixed argument lists only, no shell
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ramcove_protocol.canonical import sha256_hex
from ramcove_protocol.preflight import normalize_patch


class IsolationUnavailable(RuntimeError):
    """Required isolation or trusted measurement is unavailable. Never charged to the miner."""


@dataclass
class Readiness:
    provider: str
    online: bool
    safe_and_ready: bool
    untrusted_code_isolation: bool
    simulated: bool
    checks: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class IsolationProvider(Protocol):
    name: str

    def readiness(self) -> Readiness: ...
    def resolve_stack(self, artifact: bytes | None) -> dict[str, Any]: ...


def read_patch_from_artifact(data: bytes, max_bytes: int = 80 * 1024 * 1024) -> str:
    """Bounded read of patch.diff from a frozen artifact without extracting to disk."""
    raw = gzip.decompress(data)
    if len(raw) > max_bytes:
        raise IsolationUnavailable("artifact too large")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tf:
        member = tf.getmember("patch.diff")
        if not member.isfile():
            raise IsolationUnavailable("patch.diff is not a regular file")
        f = tf.extractfile(member)
        return f.read().decode("utf-8") if f else ""


class SimulatedTrustedProvider:
    name = "simulated-trusted-fixtures"

    def __init__(self, registry: dict[str, dict], baseline: dict) -> None:
        self.registry, self.baseline = registry, baseline

    def readiness(self) -> Readiness:
        return Readiness(
            self.name,
            True,
            True,
            False,
            True,
            [
                {"id": "provider", "ok": True, "detail": "SIMULATION: trusted repository fixtures only"},
                {
                    "id": "untrusted_code_isolation",
                    "ok": False,
                    "detail": "no VM/GPU passthrough boundary in this mode",
                },
                {"id": "gpu_measurement", "ok": True, "detail": "simulated serving model; no GPU is used"},
            ],
        )

    def resolve_stack(self, artifact: bytes | None) -> dict[str, Any]:
        if artifact is None:
            return self.baseline["params"]
        h = sha256_hex(normalize_patch(read_patch_from_artifact(artifact)).encode())
        fx = self.registry.get(h)
        if fx is None:
            raise IsolationUnavailable(
                "artifact is not a trusted fixture; the simulated provider refuses to evaluate it"
            )
        return fx["params"]


H100_PCI_IDS = {
    "10de:2330",
    "10de:2331",
    "10de:2339",
}  # candidate IDs; confirm against the actual host inventory


@dataclass(frozen=True)
class VmSpec:
    vcpus_pinned: tuple[int, ...]
    ram_gib: int
    swap: bool
    network_interfaces: tuple[str, ...]
    vfio_devices: tuple[str, ...]
    vsock_cid: int
    root_image_sha256: str
    root_readonly: bool
    env: dict[str, str]
    candidate_artifact_sha256: str


class VfioVmProvider:
    name = "vfio-vm"

    def __init__(
        self,
        gpu_bdf: str | None,
        image_sha256: str | None,
        agent_socket: str | None,
        sys_root: Path = Path("/"),
    ) -> None:
        self.gpu_bdf, self.image_sha256, self.agent_socket, self.root = (
            gpu_bdf,
            image_sha256,
            agent_socket,
            sys_root,
        )

    def _check(self, cid: str, ok: bool, detail: str) -> dict[str, Any]:
        return {"id": cid, "ok": ok, "detail": detail}

    def readiness(self) -> Readiness:
        checks = []
        kvm = (self.root / "dev/kvm").exists()
        checks.append(
            self._check(
                "kvm", kvm, "/dev/kvm present" if kvm else "/dev/kvm missing: no hardware virtualization"
            )
        )
        groups = self.root / "sys/kernel/iommu_groups"
        n_groups = len(list(groups.iterdir())) if groups.exists() else 0
        checks.append(self._check("iommu", n_groups > 0, f"{n_groups} IOMMU groups"))
        driver_ok, dev_ok = False, False
        if self.gpu_bdf:
            dev = self.root / "sys/bus/pci/devices" / self.gpu_bdf
            if dev.exists():
                vid = (dev / "vendor").read_text().strip().removeprefix("0x")
                did = (dev / "device").read_text().strip().removeprefix("0x")
                dev_ok = f"{vid}:{did}" in H100_PCI_IDS
                drv = dev / "driver"
                driver_ok = drv.exists() and os.path.basename(os.readlink(drv)) == "vfio-pci"
        checks.append(
            self._check(
                "gpu_device",
                dev_ok,
                f"H100 SXM at {self.gpu_bdf}" if dev_ok else "no configured H100 SXM device",
            )
        )
        checks.append(
            self._check(
                "vfio_bound", driver_ok, "bound to vfio-pci" if driver_ok else "GPU not bound to vfio-pci"
            )
        )
        hyp = shutil.which("qemu-system-x86_64") or shutil.which("cloud-hypervisor")
        checks.append(self._check("hypervisor", bool(hyp), hyp or "no hypervisor binary"))
        agent = bool(self.agent_socket and Path(self.agent_socket).exists())
        checks.append(
            self._check(
                "measurement_agent",
                agent,
                "trusted host-side measurement agent reachable"
                if agent
                else "trusted measurement agent not configured",
            )
        )
        img = bool(self.image_sha256)
        checks.append(
            self._check(
                "verified_image", img, "read-only verified image pinned" if img else "no pinned image"
            )
        )
        checks.append(
            self._check(
                "gpu_reset_clears_memory",
                False,
                "UNVERIFIED: requires a pattern-probe test on the real host (Stage 1)",
            )
        )
        ready = all(c["ok"] for c in checks)
        return Readiness(self.name, True, ready, ready, False, checks)

    def vm_spec(self, artifact_sha256: str, cpus: tuple[int, ...]) -> VmSpec:
        if not self.gpu_bdf or not self.image_sha256:
            raise IsolationUnavailable("VFIO provider is not configured")
        return VmSpec(
            vcpus_pinned=cpus,
            ram_gib=64,
            swap=False,
            network_interfaces=(),
            vfio_devices=(self.gpu_bdf,),
            vsock_cid=3,
            root_image_sha256=self.image_sha256,
            root_readonly=True,
            env={},
            candidate_artifact_sha256=artifact_sha256,
        )

    def resolve_stack(self, artifact: bytes | None) -> dict[str, Any]:
        r = self.readiness()
        if not r.safe_and_ready:
            failed = [c["id"] for c in r.checks if not c["ok"]]
            raise IsolationUnavailable(f"VFIO VM isolation not ready: {', '.join(failed)}")
        raise IsolationUnavailable("real GPU execution is not implemented in this build")

    @staticmethod
    def host_gpu_processes() -> list[str]:
        """Host-side view used by the measurement agent design; returns empty when nvidia-smi is unavailable."""
        exe = shutil.which("nvidia-smi")
        if not exe:
            return []
        out = subprocess.run(
            [exe, "--query-compute-apps=pid,used_memory", "--format=csv,noheader"],  # noqa: S603
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return [ln for ln in out.stdout.splitlines() if ln.strip()]
