# Work log

Newest first. Commands are the ones actually run; results are what actually happened.

## 2026-09-22 — no engine download

- By owner decision RamCove no longer hosts or scripts the engine download: `baseline/` is gone, the v0
  settings live in `config/engine_args/`, and `GET /v1/baseline` and `ramcove-miner baseline` are removed.
  Miners download only the champion's patches (`GET /v1/champion-code`, `ramcove-miner champion-code`).

## 2026-09-22 — owner question bank, flat fee, published champion code

- Flat 0.1 TAO fee (the price only sets the dollar display), no daily preflight limit, 10-minute screening,
  1-hour soak (#27). A second tighter-budget reading before a winner fails the memory check (#28).
- The owner's question bank, rotated every 7 days: fingerprint committed a day ahead, the same questions for
  every job in the week, seed published after; the champion answers each bank once per worker (#29).
- `baseline/` and public downloads of the baseline pin and each champion's code; `ramcove-miner
  champion-code` (#30). The site shows all of it (#31). `docs/adr/0010`.
- Verified: `uv run pytest` 142 passed, 2 deselected; migrations 0005 and 0006 round-trip and `alembic check`
  is clean; browser suite 14 passed against the isolated stack; `baseline/fetch.sh` checked out `98dff2a8`.

## 2026-09-22 — one evaluation against the champion's fixed score

- The champion is measured once per worker when it is crowned and not again. Each challenger gets offline
  quality and one reading against that fixed score; 5% margin, 9% clear win, one more reading in between.
  Winner checks run once, for winners only. Review happens only when an automatic check flags a winner.
  A winner measured against an older champion is re-compared by arithmetic. No confirmation blocks,
  rebases, evaluation deadline or waiting refunds (#20, `docs/adr/0009`).
- Booking per paid submission is the expected work of one evaluation (3.34 GPU-hours); fee basis $15.63
  (0.04 TAO at $227.92). Migration 0004.
- Fixed while checking end to end: a second reading's seed did not fit its column (#21, caught by CI); the
  champion's score search began at a fixed rate, so two workers scored the same champion 50% apart, and a
  six-rate cap on readings made strong winners look equal (#22). The site shows the new flow (#23).
- Verified: `uv run pytest` 128 passed, 2 deselected; migrations up, down, up and `alembic check` clean;
  browser suite 14 passed and `node screenshots.mjs` 12 views with no problems, against the isolated stack.
- Measured (`docs/acceptance-matrix.md`): clearly better fixtures won 17 of 24 evaluations and the ones that
  should lose won 0 of 32. The simulator's drift gate fails up to a quarter of runs below capacity, and the
  champion's tighter-budget score is noisy enough that in two of six seeds no stack reached it.

## 2026-09-19 — a read-only site; every role uses its own tool

- The website has no sign-in any more. Miners submit with `ramcove-miner`, validators run `ramcove-worker`,
  and the operator, reviewers and appeal panel act with the new `ramcove-operator`, each with their own key.
- Retired pages (Submit, My work, Validator, Review, Operator) redirect to where their content lives; the
  public submission page stays, without the author's payment details. The browser no longer talks to the
  API at all, so the Next.js proxy route is gone.
- The public door (nginx :8788) now accepts only `GET` and `HEAD`, and refuses sign-in, miner and demo
  routes on top of the role workspaces. Guest sign-in is removed; migration 0003 drops its table and the
  throwaway keys in it.
- The whitepaper opens full screen as the PDF from the header, the Docs tabs and the footer.
- Docs gained command-line guides for miners and validators, stating plainly that real GPU execution and
  a real-network signer are not in this build.
- Verified: `uv run pytest` 121 passed, 2 deselected (the opt-in live-network tests); browser suite 14 passed (7 journeys × desktop and phone)
  against an isolated stack (API :8797 on database `ramcove_e2e`, dev web :3797), so the live demo data
  was not touched; `node screenshots.mjs` 12 views, 0 with problems.

## 2026-09-18 — browser verification and demo scenarios

- Browser suite (`apps/web/e2e/journeys.spec.ts`): 16 tests pass on desktop (1440×900) and phone (Pixel 7).
  A global setup resets the labelled demo dataset so runs are repeatable.
- Screenshot verification (`node screenshots.mjs`): 18 views captured, 0 with console errors, horizontal
  page overflow or dead buttons. Output in `docs/screenshots/`.
- Fixed from the browser evidence: mobile horizontal overflow, a hydration mismatch from relative
  timestamps, a theme toggle that set state in an effect, a review timestamp rendering as `[object Object]`,
  cramped navigation labels.
- Demo fixtures gained labelled variants so a local demonstration can be repeated; real artifacts get no
  such help and duplicate detection applies to them unchanged.

## 2026-09-17 — protocol, services, evaluator, API, web

- Protocol core with unit tests (58 passing): replacement bound reproduces the whitepaper's worked
  examples within 0.05 percentage points; fixed quality reference stops small losses accumulating; the
  promotion barrier covers every earlier active paid admission; conservative reservations bound a flood of
  strong submissions; fee rounding, UID reuse, archive attacks and every payment rejection path.
- PostgreSQL schema and migration (35 tables), append-only hash-chained audit log with a database trigger.
- Services: preflight, waiting list, quotes, payment verification to exactly-once receipt and admission,
  leases, settlement with an atomic champion check-and-set, rebase, registration gate, review and appeals,
  credits and refunds, proposed weight plans.
- Evaluator: seeded task generation, deterministic grading, open-loop schedules, per-run and pooled gates,
  grid capacity search with defined boundaries, paired blocks, memory evidence, P-live.
- Worker: isolation-provider interface, simulated trusted-fixture provider, VFIO VM provider that probes
  the host and fails closed.
- HTTP API (43 routes) with hotkey sign-in, worker request signing, idempotency and role checks; 9 HTTP
  tests pass.
- Protocol safety suite (13 tests) against PostgreSQL: concurrent quotes cannot oversell capacity, replays
  cannot admit twice, promotion order holds, two promotions cannot both win, stale evidence is rebased.
- Web application: design tokens, overview, competition, queue, guided submission, submissions and detail,
  validator, review, operator, docs, status.

### Decisions that changed the whitepaper's rules

- Memory evidence: the paper's "gain stays within 2 points of the full-budget gain" is not measurable at
  the grid resolution used, so the gate became "the gain must still exceed the replacement margin under a
  25% smaller cache budget", with the original comparison reported as evidence (`docs/adr/0007`).
- The external memory probe decides; reduced recomputation is reported but never sufficient on its own,
  because a faster stack also recomputes less.

### Honest findings

- Validating the memory diagnostics against known methods: both compute-only methods are correctly
  rejected; two of three memory methods pass. A retention-only method is a **false negative**.
- In the simulator, a fixture measured +23% in triage and a +14.3% confirmed lower bound in one run, and
  −1.2% in another. That spread is why the margin and the paired blocks exist, and why the paper's single
  estimates cannot be trusted before a real noise study.

## Next executable steps

1. Real-hardware Stage 1: measure noise, runtimes and the memory diagnostics on one H100 SXM; replace every
   provisional value in `config/profiles/ramcove-p1@1.0.0.json`.
2. Testnet: exercise `batch_all` payment verification, weight publication and the no-winner path with an
   authorized signer.
3. Implement a real isolation backend behind `VfioVmProvider` and run the conformance checks on the host.
