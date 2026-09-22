# ADR 0009 — One evaluation per submission against the champion's fixed score

**Status:** accepted, 2026-09-22. The whitepaper was revised to match (Sections 7, 8.9, 9.2 and 10.5).

**Context.** Each promotion used to need a triage evaluation, five paired confirmation blocks and a human
review: about 62 GPU-hours booked per paid admission and up to ten business days of review. The champion was
re-measured in every block and recalibrated weekly. The owner asked for a faster, simpler flow.

**Decision.**
- The champion is measured once per worker when it is crowned (capacity confirmed by three fresh runs,
  tighter-budget capacity, short-request baseline) and not again within a profile version. Scores are kept
  per worker because physical GPUs differ.
- A challenger gets one evaluation: offline quality, then one reading that steps up a 3% grid from the fixed
  score until a rate fails. At or below 5% loses, at or above 9% wins, and in between one more reading
  decides (the average must exceed 5%). Winner checks run once each, for winners only.
- Promotion is automatic unless an automatic check flags the winner (native code, third-party components,
  a check's flag). Only flagged winners are reviewed.
- A queued challenger runs against the champion current at its turn. A winner measured against an older
  champion is re-compared by arithmetic, `(1 + G) / (1 + G_new) − 1`; nothing is measured again. A rules
  change or a rollback re-runs the evaluation at the same key with no new fee.
- Each paid submission books the expected work of one evaluation (3.34 GPU-hours); the two-week cap limits
  the queue, and a queued paid submission is always evaluated.

**Consequences.** An evaluation takes about 3 GPU-hours instead of about 9 plus 14 for confirmation, and the
queue holds about twenty times more submissions per worker. The price is that every comparison on a worker
leans on one measurement of the champion: a score that comes out high rejects every challenger on that
worker until the next champion, and one that comes out low lets weaker challengers win. In the simulator
this noise is large (`docs/acceptance-matrix.md`, rows 12 and 13); on real hardware the Stage 1 study must
show that the fixed score and a single reading are measured within about 2% before paid submissions open.
Readings are never cut short, because arithmetic re-comparison needs uncapped gains.
