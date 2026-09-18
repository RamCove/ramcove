"""Sign-in challenges for hotkey-based sessions (``ramcove.signin/1``).

The message binds domain, network, genesis hash, hotkey, nonce, issue time and expiry, so a
signature cannot be replayed on another site, network or after expiry. Nonces are single use
(enforced by the database). Signature verification is injected, keeping this module chain-SDK free.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

Verifier = Callable[[str, bytes, bytes], bool]  # (ss58 hotkey, message, signature) -> ok


@dataclass(frozen=True)
class Challenge:
    domain: str
    network: str
    genesis_hash: str
    hotkey: str
    nonce: str
    issued_at: datetime
    expires_at: datetime

    def message(self) -> bytes:
        return (
            f"RamCove sign-in\n"
            f"domain: {self.domain}\n"
            f"network: {self.network}\n"
            f"genesis: {self.genesis_hash}\n"
            f"hotkey: {self.hotkey}\n"
            f"nonce: {self.nonce}\n"
            f"issued: {self.issued_at.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
            f"expires: {self.expires_at.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
            f"This signature only signs in. It does not authorize any payment or transfer."
        ).encode()


class ChallengeError(ValueError):
    pass


def verify_challenge(
    ch: Challenge,
    signature: bytes,
    verifier: Verifier,
    now: datetime,
    expected_domain: str,
    expected_network: str,
    expected_genesis: str,
) -> None:
    if ch.domain != expected_domain:
        raise ChallengeError("challenge domain mismatch")
    if ch.network != expected_network or ch.genesis_hash != expected_genesis:
        raise ChallengeError("challenge network mismatch")
    if now >= ch.expires_at:
        raise ChallengeError("challenge expired")
    if not verifier(ch.hotkey, ch.message(), signature):
        raise ChallengeError("signature does not verify for this hotkey")
