# ADR 0015 — Submitting is free

**Status:** accepted, 2026-11-04. Owner decision; supersedes ADR 0004 and the flat fee in ADR 0010.

**Context.** A miner paid a flat 0.1 TAO per submission: the service issued a quote, the miner paid it with a
`batch_all` transfer and remark, the controller verified the finalized payment and admitted the submission,
and the fee was consumed, refunded or credited according to the outcome. The owner wants submissions to be
free.

**Decision.**
- There is no submission fee, quote, payment, receipt, refund, credit or fee ledger. The owner bears the
  evaluation workers' GPU time.
- A submission that passes the free checks joins the queue with one call, `intake.admit`. It is admitted
  when evaluation capacity is free, or placed on the free waiting list and invited in order, as before.
- Joining the queue needs a hotkey registered on the subnet; the free checks do not. Registration is the
  remaining cost of entry, and it is the hotkey that would receive weight. One active submission per hotkey
  and per lineage, the two-week capacity cap and the operator's intake pause stay.
- The admission key is the finalized block at admission and the order of admission within that block,
  assigned under a lock so keys are unique. The service returns a signed admission record
  (`ramcove.admission/1`) in place of the receipt.
- The `quoted` and `expired_quote` states, the fee outcome of each terminal state and the fee policy in the
  profile go. Migration 0008 drops the fee tables and the price observations; it returns a quoted submission
  to `preflight_passed` and closes an expired quote as `withdrawn`.
- `ramcove-miner submit` runs the free checks and joins the queue; `recover` goes. The operator's refund
  commands go.

**Consequences.** Trying an idea costs a miner nothing but the registration, so more attempts reach the
queue; the capacity cap and the one-active-submission rule keep that within the owner's GPU budget, and the
waiting list absorbs the rest. The profile's rule hash changes, so existing databases are reset.
