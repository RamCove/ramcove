"""ramcove-validator: a CPU-only validator that sets weights from the owner's signed results.

    ramcove-validator --api https://<owner host>:8788 --key-uri //YourDevKey          # simulation mode
    ramcove-validator --api https://<owner host>:8788 --chain-endpoint wss://...      # network mode

Every ``--interval`` seconds it fetches ``/v1/weights/latest``, checks the owner's signature against the key
pinned for the network, maps hotkeys to UIDs from its own chain reads, and submits the weights. It needs
no GPU, no evaluation data and no database.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import httpx
from substrateinterface import Keypair

from .core import PINNED_SIGNERS, ChainView, Outcome, State, run_cycle

log = logging.getLogger("ramcove.validator")


class CliError(RuntimeError):
    pass


def verify_sr25519(address: str, message: bytes, signature: bytes) -> bool:
    try:
        return bool(Keypair(ss58_address=address).verify(message, signature))
    except (ValueError, TypeError):
        return False


def _check(r: httpx.Response) -> dict:
    if r.status_code >= 400:
        try:
            err = r.json()["error"]
            raise CliError(f"{err['code']}: {err['message']}")
        except (ValueError, KeyError):
            raise CliError(f"HTTP {r.status_code}") from None
    return r.json()


class HttpSource:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def latest(self) -> dict:
        return _check(self.client.get("/v1/weights/latest"))


class SimulatedChain:
    """The dev chain lives inside the owner's service, which answers the reads a validator makes."""

    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def view(self) -> ChainView:
        d = _check(self.client.get("/v1/validator/chain"))
        return ChainView(
            d["network"],
            d["genesis_hash"],
            d["netuid"],
            d["finalized_block"],
            d["hotkey_to_uid"],
            d["owner_hotkey"],
        )


class SimulatedSubmitter:
    """Signs in with the validator's hotkey and submits set_weights on the dev chain."""

    def __init__(self, client: httpx.Client, keypair: Keypair) -> None:
        self.client, self.keypair, self.hotkey = client, keypair, keypair.ss58_address
        self._signed_in = False

    def _sign_in(self) -> None:
        ch = _check(self.client.post("/v1/auth/challenge", json={"hotkey": self.hotkey}))
        sig = "0x" + self.keypair.sign(ch["message"].encode()).hex()
        _check(self.client.post("/v1/auth/verify", json={"nonce": ch["nonce"], "signature": sig}))
        self._signed_in = True

    def submit(self, uids: list[int], weights: list[int], version_key: int, document_hash: str) -> dict:
        if not self._signed_in:
            self._sign_in()
        body = {"uids": uids, "weights": weights, "version_key": version_key, "document_hash": document_hash}
        return _check(self.client.post("/v1/validator/weights", json=body))


class NetworkChain:
    """Reads the real chain directly: finality, genesis, UID map and subnet owner."""

    def __init__(self, endpoint: str, network: str, netuid: int) -> None:
        from ramcove_chain.network import KNOWN
        from ramcove_chain.substrate_reader import SubstrateReader

        if network not in KNOWN or KNOWN[network].simulated:
            raise CliError(f"unknown network {network!r}")
        self.network, self.netuid = network, netuid
        self.reader = SubstrateReader(endpoint, KNOWN[network])

    def view(self) -> ChainView:
        block, uids = self.reader.hotkey_uid_map(self.netuid)
        return ChainView(
            self.network,
            self.reader.genesis_hash(),
            self.netuid,
            block,
            uids,
            self.reader.subnet_owner_hotkey(self.netuid),
        )


class NetworkSubmitter:
    def __init__(self, hotkey: str, network: str) -> None:
        self.hotkey, self.network = hotkey, network

    def submit(self, uids: list[int], weights: list[int], version_key: int, document_hash: str) -> dict:
        raise CliError(
            f"submitting weights on {self.network} is a launch step: this build reads the network but does not "
            "write to it (see the README's Launch section)"
        )


def _report(o: Outcome) -> None:
    level = logging.INFO if o.action in ("submitted", "up_to_date") else logging.WARNING
    extra = {k: v for k, v in o.detail.items() if k in ("block", "error", "problems", "signer", "notes")}
    log.log(level, "%s: %s %s", o.action, o.reason, extra or "")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ramcove-validator", description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--api", default="http://127.0.0.1:8787", help="the owner's API, which serves /v1/weights/latest"
    )
    p.add_argument("--key-uri", help="a development key URI (simulation mode only)")
    p.add_argument("--hotkey", help="your registered validator hotkey (network mode)")
    p.add_argument("--chain-endpoint", help="a Bittensor RPC endpoint (network mode)")
    p.add_argument("--state", default=str(Path.home() / ".ramcove" / "validator-state.json"))
    p.add_argument("--interval", type=float, default=30.0, help="seconds between cycles")
    p.add_argument("--once", action="store_true", help="run one cycle and exit")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        with httpx.Client(base_url=args.api, timeout=30.0) as client:
            # the only open paths on the owner's public door are /v1/weights/*
            meta = _check(client.get("/v1/weights/signer"))
            network = meta["network"]
            pin = PINNED_SIGNERS.get(network)
            if not pin:
                raise CliError(f"no owner signing key is pinned for {network!r} in this build")
            if meta.get("simulated_chain"):
                if not args.key_uri:
                    raise CliError("simulation mode needs --key-uri, a development key")
                kp = Keypair.create_from_uri(args.key_uri)
                chain, submitter = SimulatedChain(client), SimulatedSubmitter(client, kp)
            else:
                if args.key_uri:
                    raise CliError("--key-uri is a development key; use --hotkey with a real network")
                if not (args.chain_endpoint and args.hotkey):
                    raise CliError("network mode needs --chain-endpoint and --hotkey")
                chain = NetworkChain(args.chain_endpoint, network, int(meta.get("netuid", 0)))
                submitter = NetworkSubmitter(args.hotkey, network)
            log.info("validator %s on %s; owner signer pinned %s", submitter.hotkey, network, pin)
            state = State.load(Path(args.state))
            while True:
                try:
                    _report(run_cycle(HttpSource(client), chain, submitter, state, pin, verify_sr25519))
                except (CliError, httpx.HTTPError) as e:
                    log.warning("cycle failed: %s", e)
                if args.once:
                    return 0
                time.sleep(args.interval)
    except CliError as e:
        print(f"ramcove-validator: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
