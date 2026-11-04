# ADR 0010 — The owner's weekly question bank, a flat fee, and published champion code

**Status:** accepted, 2026-09-22; the flat fee is superseded by ADR 0015 (submitting is free). Owner decisions.

**Context.** Questions were generated per evaluation from a public generator and a beacon seed. Nobody could
predict a given evaluation's questions, but the owner wanted the questions to come from the owner's
platform, not from validators, and to rotate on a schedule. The fee was half of a planning cost, converted
at the TAO price. Miners could not download the baseline or the champion's code to build on.

**Decision.**
- The owner platform builds one secret bank per profile every 7 days (200 screening and 4,000 quality
  questions, traffic scripts). Its fingerprint is committed to the public audit log a day ahead; jobs receive
  the week's seed, never the owner's secret; the seed is published after the week.
- Every evaluation in a week answers the same questions; each reading's traffic also mixes in its own beacon
  seed. The champion answers each bank once per worker instead of once per evaluation.
- The fee is a flat 0.1 TAO per paid submission; the price is used only for the dollar display. There is no
  daily preflight limit; one active submission per hotkey remains.
- Screening is 10 minutes of GPU time; the winner's soak is 1 hour.
- `baseline/` documents champion v0 and fetches it; `GET /v1/baseline` and `GET /v1/champions/<v>/artifact`
  publish the baseline pin and each promoted champion's code; `ramcove-miner champion-code` downloads it.

**Consequences.** Evaluations are cheaper (about 2.2 GPU-hours) and every submission in a week is compared on
identical questions. During a week the validators hold its bank, so a dishonest validator could leak it; the
weekly rotation, the public reveal and the per-reading beacon seed limit a leak's value but do not prevent
it. The owner's secret becomes a critical key (`RAMCOVE_BANK_SECRET`). At full utilization the flat fee
covers about twice the planning cost; it no longer follows the TAO price.

**Update, later on 2026-09-22.** The owner decided RamCove should not host or script a download of the
engine: `baseline/` was removed and its settings moved to `config/engine_args/`. Miners download only the
champion's patches (`GET /v1/champion-code`, `ramcove-miner champion-code`) and apply them to the engine at
the pinned commit themselves.
