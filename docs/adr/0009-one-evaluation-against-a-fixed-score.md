# ADR 0009 — One evaluation per submission against the champion's fixed score

**Status:** accepted, 2026-09-22.

**Context.** Each promotion used to need a triage evaluation, five paired confirmation blocks and a human
review: about 62 GPU-hours booked per admission and up to ten working days of review. The champion was
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
- Each paid submission books screening plus the expected work of one evaluation (2.41 GPU-hours,
  updated from 3.34 when the run lengths were brought in line with Appendix B); the two-week cap limits
  the queue, and a queued paid submission is always evaluated.

**Consequences.** An evaluation takes about 2.2 GPU-hours instead of about 9 plus 14 for confirmation, and the
queue holds about twenty times more submissions per worker. The price is that every comparison on a worker
leans on one measurement of the champion: a score that comes out high rejects every challenger on that
worker until the next champion, and one that comes out low lets weaker challengers win. In the simulator
this noise is large; on real hardware the calibration must
show that the fixed score and a single reading are measured within about 2% before the profile opens.
Readings are never cut short, because arithmetic re-comparison needs uncapped gains.
