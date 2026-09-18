# Runbook: unsafe champion and rollback

Use this when a promoted champion turns out to be unsafe or wrong.

## Decide

- Is the flaw deliberate? If yes, the lineage is excluded and the appeal path still applies to the author.
- Is the flaw in the champion's code, or in the evaluator? An evaluator fault is an incident, not a
  rollback: the affected comparisons are voided and rerun at operator cost.

## Act

1. Open an incident first, with a public summary that names the effect on miners and customers.
2. Pause paid admissions if the fault could affect measurements.
3. `/operator` → Controls → **Suspend and roll back**, with a reason of at least ten characters and the
   deliberate flag set honestly.

What that does: the current champion becomes `rolled_back` and keeps its evidence; the previous reviewed
stack becomes current under a **new** version number; every pending comparison is rebased onto it with fresh
blocks, keeping admission keys and charging no new fee; workers lose their calibration and recalibrate;
weight goes to no winner until a challenger qualifies, and the chain burns that share.

4. Tell the affected miners on their submission pages — the rebase reason is already published there.
5. Resume admissions only when a worker is safe-and-ready and the evaluator version is pinned.

## What you must not do

Do not hand-pick a replacement champion, edit a score, or delete the suspended version. The rollback path
exists so that the safe stack returns without erasing the record of what happened.
