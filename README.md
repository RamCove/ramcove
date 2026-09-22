# RamCove — More AI. Same GPU.

RamCove is a Bittensor subnet that pays for independently verified software improvements which
let one fixed GPU serve more useful AI requests, by using its memory better. Miners submit reviewable
code. Validators build it in controlled environments and measure *qualified serving capacity* against the
current champion's fixed score, once per submission. One champion per profile holds that profile's miner
allocation until a challenger proves a real improvement; a person reviews a winner only when an automatic
check flags it.

This repository is a **local development build**. Nothing here has been measured on an H100, no real tokens
move, and mainnet writes are disabled. Every simulated component says so in the code, the API and the
interface.

| Part | What it is |
|---|---|
| `packages/protocol` | Pure rules: lifecycle, replacement rule, promotion order, reservations, fees, weights, preflight |
| `packages/evaluator` | Task generation, grading, open-loop load, gates, the champion's fixed score, capacity readings, memory evidence |
| `baseline` | Champion version 0: the pinned engine, its settings, and scripts to fetch it and apply the champion's patches |
| `packages/chain` | Payment verification, deterministic dev chain (simulation), read-only Bittensor adapter, drand scheduling |
| `services/api` | FastAPI surface, authoritative PostgreSQL store, transactional services |
| `services/controller` | Loop: chain observation, payment verification, expiries, settlement |
| `services/worker` | Isolation providers and stage execution; never runs candidate code outside a provider |
| `miner_cli` | `ramcove-miner`: reproducible packing, free checks, quote, payment, recovery |
| `services/api/ramcove_api/operator_cli.py` | `ramcove-operator`: the operator's and reviewers' controls, each signed with their own key |
| `apps/web` | Next.js site, read-only: overview, dashboard, submission pages, docs and rules, status |

## Public demo

The hosted site, https://ramcove.vercel.app, is the web app on Vercel reading a live backend on the
operator's host: the same competition as the local stack, updated live. The site is read-only and has no
sign-in. Miners submit with `ramcove-miner`, validators run `ramcove-worker`, and the operator and
reviewers act with `ramcove-operator`, each with their own key. How it is wired, secured and operated is in
[`docs/runbooks/public-demo.md`](docs/runbooks/public-demo.md).

If the hosted site has no backend configured it falls back to a labelled, read-only snapshot
(`apps/web/src/preview/snapshot.json`, refreshed with `cd apps/web && npm run snapshot`).

The code lives at https://github.com/RamCove/ramcove, and the whitepaper is served with the site at
`/whitepaper/RamCove_Whitepaper_v0.2.pdf`.

## Run it locally

Requirements: Docker (for PostgreSQL), Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 20.

```bash
make setup     # install Python and web dependencies
make db        # start PostgreSQL 17 and apply migrations
make seed      # labelled demo dataset
make dev       # API :8787, controller, two simulated workers, web app :3787
```

Open http://localhost:3787 to follow the competition. To take part, use the command line with the
published development keys (local build only):

```bash
uv run ramcove-miner submit --artifact artifact.tar.gz --key-uri //RamCoveDemoMinerAda
uv run ramcove-operator --key-uri //RamCoveDemoOperator console
uv run ramcove-operator --key-uri //RamCoveDemoReviewerOne reviews
```

```bash
uv run ramcove-admin scenario --list   # seeded scenarios
uv run ramcove-admin scenario busy     # drives the real services; takes a few minutes
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
