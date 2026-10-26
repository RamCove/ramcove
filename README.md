# RamCove — More AI. Same GPU.

RamCove is a Bittensor subnet that pays for independently verified software improvements which
let one fixed GPU serve more useful AI requests, by using its memory better. Miners submit reviewable
code. Validators build it in controlled environments and measure *qualified serving capacity* against the
current champion's fixed score, once per submission. Each profile runs king of the hill: a challenger that
proves a real improvement becomes King #1, and the five most recent kings each earn 20% of that profile's miner
allocation until they fall out of the queue. A person reviews a winner only when an automatic check flags it.

**[How a submission is evaluated](docs/evaluation.md)** walks the whole path — free checks, screening,
question quality, the capacity reading, the rule and the winner checks — with the number that decides each
step and why each step exists.

This repository is the RamCove subnet: the miner tool, the validator's evaluation worker, and the owner's
intake, queue, controller, API and website. It runs in two modes, chosen by configuration:

- **Simulation mode** (`RAMCOVE_ENV=demo`), which the public demo at https://ramcove.vercel.app uses: a
  deterministic dev chain, a simulated beacon and simulated GPU workers, so the whole competition can be
  run end to end on one machine. Every number that comes from the simulation is labelled as such.
- **Network mode** (`RAMCOVE_ENV=testnet`, then mainnet): the worker's VFIO provider runs candidates in a
  hardware VM on a whole H100 SXM, and payments, weights and the audit anchor go to the chain. The steps
  that switch it on are in [Launch](#launch).

| Part | What it is |
|---|---|
| `packages/protocol` | Pure rules: lifecycle, replacement rule, promotion order, reservations, fees, weights, preflight |
| `packages/evaluator` | Task generation, grading, open-loop load, gates, the champion's fixed score, capacity readings, memory evidence |
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
published development keys (simulation mode):

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

- `docs/evaluation.md` — the whole evaluation workflow, step by step, and why each step is there
- `docs/spec/protocol.md` — the corrected protocol, rule by rule
- `docs/adr/` — architecture decisions, including where the implementation deviates from the whitepaper and why
- `docs/guides/` — miner, validator and operator guides
- `docs/runbooks/` — deployment, backup and recovery, refunds, rollback, incidents

## Launch

Moving from simulation mode to the network is a sequence of steps:

1. **GPU measurement.** Enable the VFIO provider on validator hosts with a whole H100 SXM and run the Stage 1
   calibration: the tuned baseline's score, the noise study that sets the margin, and the published run
   times. Until then the worker's simulated provider evaluates the trusted repository fixtures.
2. **Subnet registration** on testnet, then mainnet, which fixes the netuid the tools and the site use.
3. **Payments and weights.** Point the controller at the network's finalized blocks for fee payments,
   and switch weight plans from proposed to submitted through commit-reveal.
4. **Customer releases** of the reference stack, on the quarterly cadence the whitepaper describes.
