# ADR 0001 — Modular monorepo with a pure protocol core

**Status:** accepted, 2026-09-17

**Context.** The competition's rules decide who is paid. They must be testable without a database, an HTTP
server or a chain, and they must be readable by any miner or validator checking how a result is decided.

**Decision.** One repository, with `packages/protocol` holding pure rules (no HTTP, no SQL, no chain SDK),
`packages/evaluator` and `packages/chain` holding measurement and chain shapes, `services/*` holding the
transactional application, `miner_cli` and `apps/web` holding the two user surfaces.

**Consequences.** Rule changes are unit-tested in milliseconds and reviewed in one place. Services convert
database rows into the protocol's dataclasses. The cost is some conversion code at the boundary, which is
the point: the rules cannot quietly depend on storage details.
