# ADR 0003 — A deterministic dev chain and beacon, always labelled

**Status:** accepted, 2026-09-17

**Context.** The protocol depends on finalized payments and on randomness that nobody can choose. Local
development must exercise both, without touching a real network or real funds.

**Decision.** `room_chain.devchain` produces blocks, extrinsics and events in exactly the shapes the real
reader produces, including failure modes (plain `batch` interruption, insufficient balance, wrong remark).
`room_chain.beacon.DevBeacon` produces deterministic randomness. Both set `simulated: true`, the API
repeats it in `/v1/meta`, and the interface shows a banner and per-value tags.

**Consequences.** The payment verifier and the scheduling logic are exercised end to end offline. A
simulated component can never be mistaken for a real one, and a simulated worker is refused readiness on a
real network (`room_api.services.workers.heartbeat`).
