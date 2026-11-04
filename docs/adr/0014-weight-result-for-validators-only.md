# ADR 0014 — The weight result is served only to validators

**Status:** accepted, 2026-11-04. Owner decision; refines ADR 0012. The whitepaper was revised to match.

**Context.** ADR 0012 served the owner's signed weight result at `GET /v1/weights/latest` to anyone, and the
public site listed the proposed weights by hotkey and UID. The owner wants the scores that validators set
weights from to be visible to validators only.

**Decision.**
- Every read of the weight result is signed with the reader's hotkey: an sr25519 signature over
  `fetch_payload(network, hotkey, timestamp, path)`, sent as `x-ramcove-hotkey`, `x-ramcove-timestamp` and
  `x-ramcove-signature`. The owner accepts a timestamp within 120 seconds of its own clock.
- The hotkey must hold a validator permit: on a network, `SubtensorModule.ValidatorPermit` for its UID on the
  subnet (`SubstrateReader.validator_permit_hotkeys`); in simulation, where the dev chain has no stake, a
  hotkey in the owner's validators table that is registered on the dev chain. Until the service reads the
  network (launch step 3) the check refuses every read in network mode.
- Errors are explicit: `401 validator_signature_required`, `401 stale_request`, `401 bad_signature` and
  `403 not_a_validator`. `GET /v1/weights/signer` holds no scores and stays open.
- The public site keeps the king queue (masked hotkeys, slots and shares) and the weight plan's status and
  notes, and drops the weights by hotkey and UID. The public audit event for a validator's submission records
  the block and the number of weights, not the vectors.
- `ramcove-validator` signs every read. In network mode it stops with a clear message until launch step 3,
  which loads the validator's hotkey for both reading and submitting.

**Consequences.** Non-validators cannot fetch the signed result or read weights from the site. The weights a
validator submits are on the chain, visible to anyone once revealed, as on every subnet; commit-reveal keeps
them hidden until the reveal. The king queue stays public because miners need to know whom to beat. A
captured signed request can be replayed only within its two-minute window and only against the same path.
