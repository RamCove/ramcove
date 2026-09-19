# Work log

Newest first. Commands are the ones actually run; results are what actually happened.

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
