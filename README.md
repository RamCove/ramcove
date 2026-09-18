# ROOM — More AI. Same GPU.

ROOM is a **proposed** Bittensor subnet that pays for independently verified software improvements which
let one fixed GPU serve more useful AI requests, by using its memory better. Miners submit reviewable
code. Validators build it in controlled environments and measure *qualified serving capacity* against the
current champion. One champion per profile holds that profile's miner allocation until a challenger proves
a real improvement and passes human review.

This repository is a **local development build**. Nothing here has been measured on an H100, no real tokens
move, and mainnet writes are disabled. Every simulated component says so in the code, the API and the
interface.

| Part | What it is |
|---|---|
| `packages/protocol` | Pure rules: lifecycle, replacement bound, promotion order, reservations, fees, weights, preflight |
| `packages/evaluator` | Task generation, grading, open-loop load, gates, capacity search, paired blocks, memory evidence |
| `packages/chain` | Payment verification, deterministic dev chain (simulation), read-only Bittensor adapter, drand scheduling |
| `services/api` | FastAPI surface, authoritative PostgreSQL store, transactional services |
| `services/controller` | Loop: chain observation, payment verification, expiries, settlement |
| `services/worker` | Isolation providers and stage execution; never runs candidate code outside a provider |
| `miner_cli` | `room-miner`: reproducible packing, free checks, quote, payment, recovery |
| `apps/web` | Next.js application: overview, competition, queue, submission flow, validator, review, operator, docs |

## Run it locally

Requirements: Docker (for PostgreSQL), Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 20.

```bash
make setup     # install Python and web dependencies
make db        # start PostgreSQL 17 and apply migrations
make seed      # labelled demo dataset
make dev       # API :8787, controller, two simulated workers, web app :3787
```

Open http://localhost:3787. Sign in with a demo identity (local build only) from the sign-in dialog.

```bash
uv run room-admin scenario --list   # seeded scenarios
uv run room-admin scenario busy     # drives the real services; takes a few minutes
make reset                          # wipe and reseed
make stop                           # stop background processes
```

### Tests

```bash
make test        # unit tests, no database needed
make test-all    # unit plus PostgreSQL-backed integration tests
make e2e         # browser journeys against a running stack
uv run pytest -m chain_readonly     # read-only queries against the public Bittensor RPC
```

`make lint` runs ruff, eslint and the TypeScript checker.

## Documentation

- `docs/spec/protocol.md` — the corrected protocol, rule by rule
- `docs/requirements-matrix.md` — whitepaper and review requirements mapped to code, tests and status
- `docs/readiness-report.md` — what is implemented, simulated, externally verified or blocked
- `docs/acceptance-matrix.md` — every claim with the command that produced it, and the measured numbers
- `docs/threat-model.md`, `docs/integration-readiness.md`
- `docs/adr/` — architecture decisions, including where this build deviates from the whitepaper and why
- `docs/guides/` — miner, validator and operator guides
- `docs/runbooks/` — deployment, backup and recovery, refunds, rollback, incidents
- `docs/screenshots/` — browser verification screenshots

## What this build does not do

- It does not measure a real GPU. The worker's simulated provider only evaluates trusted repository
  fixtures; the VFIO virtual-machine provider probes the host and fails closed.
- It does not write to any chain. Weight plans are produced and shown, never submitted.
- It does not take real payments. The dev chain is deterministic and local.
- It has no customer portal, no inference API and no registered subnet.
