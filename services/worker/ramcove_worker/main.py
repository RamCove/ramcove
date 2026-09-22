"""Evaluation worker: heartbeat, lease, execute in an isolation provider, report.

The worker talks to the API over HTTP with its own signing key. It never holds database credentials,
chain keys or GitHub tokens, and it never executes candidate code outside the provider.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import signal
import time
from typing import Any

import httpx
from ramcove_protocol.canonical import signing_payload
from ramcove_protocol.rules import ProfileVersion
from substrateinterface import Keypair

from .isolation import IsolationProvider, SimulatedTrustedProvider, VfioVmProvider
from .runner import execute

log = logging.getLogger("ramcove.worker")
_stop = False


def _handle(signum, _frame):  # noqa: ANN001
    global _stop
    _stop = True


class WorkerClient:
    def __init__(self, base_url: str, worker_id: str, keypair: Keypair, network: str) -> None:
        self.base, self.id, self.kp, self.network = base_url.rstrip("/"), worker_id, keypair, network
        self.http = httpx.Client(timeout=120.0)

    def _headers(self, method: str, path: str, body: bytes) -> dict[str, str]:
        ts = int(time.time())
        payload = signing_payload(
            "worker_request",
            self.network,
            {
                "worker": self.id,
                "method": method,
                "path": path,
                "timestamp": ts,
                "body_sha256": hashlib.sha256(body).hexdigest(),
            },
        )
        return {
            "x-ramcove-worker": self.id,
            "x-ramcove-timestamp": str(ts),
            "x-ramcove-signature": "0x" + self.kp.sign(payload).hex(),
            "content-type": "application/json",
        }

    def post(self, path: str, body: dict[str, Any]) -> dict:
        raw = json.dumps(body, default=list).encode()
        r = self.http.post(self.base + path, content=raw, headers=self._headers("POST", path, raw))
        r.raise_for_status()
        return r.json()

    def get_bytes(self, path: str) -> bytes:
        r = self.http.get(self.base + path, headers=self._headers("GET", path, b""))
        r.raise_for_status()
        return r.content

    def get_json(self, path: str) -> dict:
        r = self.http.get(self.base + path)
        r.raise_for_status()
        return r.json()


def progress_reporter(client: WorkerClient, job_id: str, pace_s: float):
    """Tell the API where the stage is, at most once a second. Progress is display only, so a failed post is
    logged and forgotten rather than retried: the next event replaces it.

    ``pace_s`` is for the public demonstration only. A simulated evaluation finishes in seconds, which would
    leave the dashboard with nothing to show, so the demonstration slows each step to about real time.
    """
    last = {"at": 0.0, "step": None}

    def report(event: dict) -> None:
        if pace_s:
            time.sleep(pace_s)
        now_s = time.monotonic()
        if event.get("step") == last["step"] and now_s - last["at"] < 1.0:
            return
        last["at"], last["step"] = now_s, event.get("step")
        try:
            client.post(f"/v1/worker/jobs/{job_id}/progress", {"event": event})
        except httpx.HTTPError:
            log.debug("progress not delivered", exc_info=True)

    return report


def build_provider() -> IsolationProvider:
    kind = os.environ.get("RAMCOVE_WORKER_PROVIDER", "simulated")
    if kind == "vfio-vm":
        return VfioVmProvider(
            os.environ.get("RAMCOVE_GPU_BDF"),
            os.environ.get("RAMCOVE_VM_IMAGE_SHA256"),
            os.environ.get("RAMCOVE_MEASUREMENT_AGENT_SOCKET"),
        )
    if kind != "simulated":
        raise SystemExit(f"unknown provider {kind!r}")
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    data = json.loads((root / "fixtures/trusted_fixtures.json").read_text())
    registry = {k: v for k, v in data.items() if not k.startswith("_")}
    return SimulatedTrustedProvider(registry, data["_baseline"])


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)
    worker_id = os.environ.get("RAMCOVE_WORKER_ID", "w-op-1")
    base = os.environ.get("RAMCOVE_API_ORIGIN", "http://127.0.0.1:8787")
    network = os.environ.get("RAMCOVE_WORKER_NETWORK", "ramcove-devchain")
    uri = os.environ.get("RAMCOVE_WORKER_KEY_URI")
    if not uri:
        raise SystemExit(
            "RAMCOVE_WORKER_KEY_URI is required (a development URI in demo mode; a real signer otherwise)"
        )
    client = WorkerClient(base, worker_id, Keypair.create_from_uri(uri), network)
    provider = build_provider()
    log.info("worker %s starting with provider %s", worker_id, provider.name)
    idle = float(os.environ.get("RAMCOVE_WORKER_IDLE_S", "3"))
    # demonstration only: 0 runs the simulation at full speed
    pace_s = float(os.environ.get("RAMCOVE_WORKER_DEMO_PACE_S", "0"))
    while not _stop:
        try:
            readiness = provider.readiness().as_dict()
            client.post("/v1/worker/heartbeat", {"readiness": readiness})
            if not readiness["safe_and_ready"]:
                log.warning(
                    "worker is not safe and ready: %s", [c for c in readiness["checks"] if not c["ok"]]
                )
                time.sleep(idle * 3)
                continue
            job = client.post("/v1/worker/lease", {}).get("job")
            if not job:
                time.sleep(idle)
                continue
            profile = ProfileVersion.model_validate(client.get_json("/v1/profile")["profile"])
            log.info(
                "leased %s stage=%s submission=%s", job["job_id"], job["stage"], job.get("submission_id")
            )
            result = execute(
                job,
                provider,
                profile,
                lambda sha: client.get_bytes(f"/v1/worker/artifacts/{sha}"),
                progress_reporter(client, job["job_id"], pace_s),
            )
            client.post(
                f"/v1/worker/jobs/{job['job_id']}/complete",
                {"result": json.loads(json.dumps(result, default=list))},
            )
            log.info("completed %s", job["job_id"])
        except httpx.HTTPError:
            log.exception("API call failed; retrying")
            time.sleep(idle * 2)
        except Exception:  # noqa: BLE001
            log.exception("worker loop error")
            time.sleep(idle * 2)
    log.info("worker stopped")


if __name__ == "__main__":
    run()
