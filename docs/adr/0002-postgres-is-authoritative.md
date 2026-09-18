# ADR 0002 — PostgreSQL is authoritative for admissions, payments and the champion

**Status:** accepted, 2026-09-17

**Context.** Admission order, "who paid", and "who is champion" must survive restarts and concurrent
requests. A cache or an event stream must never decide them.

**Decision.** One PostgreSQL database holds the authoritative state. Invariants are enforced by the schema:
unique admission keys, one open quote per submission, one verified payment per quote, one receipt per
payment reference, partial unique indexes for one active submission per hotkey and per lineage, and a
single current champion per profile. Concurrency uses transactions, `SELECT … FOR UPDATE`, `SKIP LOCKED`
for worker leases, transaction-scoped advisory locks for capacity and settlement, and idempotency keys for
externally retried calls.

**Consequences.** Races fail as constraint violations rather than as double payments. Tests can therefore
assert behaviour under real concurrency (`tests/integration/test_protocol_safety.py`). Horizontal scaling
of writes is bounded by one database, which is the right trade for this stage.
