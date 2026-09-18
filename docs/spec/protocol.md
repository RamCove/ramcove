# ROOM protocol, as implemented

Version 0.1 of the implementation, against ROOM whitepaper v0.2 and its review. Every rule below exists in
code; the column "where" names the module that owns it. Provisional values live in an immutable profile
version (`config/profiles/room-p1@1.0.0.json`) whose hash is recorded with every quote, comparison and
promotion.

**Nothing here is measured.** Runtimes, thresholds, capacities and costs are planning values until a Stage 1
study on real hardware replaces them.

## 1. Profile

A profile fixes everything that affects a raw capacity number: model repository and revision, engine
repository, tag and commit, image digests, driver and firmware, the single H100 SXM, the candidate VM
(16 cores, 64 GiB, no swap, no network), context limit, decoding, workloads, gates, the replacement rule,
deadlines, the fee formula and the bootstrap mode. Different hardware is a different profile; scores never
share a leaderboard. *Where: `room_protocol.rules`.*

## 2. Submission lifecycle

States and the events between them are a single table (`room_protocol.state`). Terminal states never move
again, except that an upheld appeal reopens a rejected review.

```
preflight_passed → waitlisted ⇄ invited → quoted → admitted → screening → eval_queued → evaluating
  → confirm_queued → confirming → in_review → ready_for_promotion → promoted
```

Exits: `rejected_preflight`, `rejected_screen`, `not_promoted`, `review_rejected`, `expired_quote`,
`expired_unregistered`, `operator_failed`, `withdrawn`.

### 2.1 Free preflight

No candidate code is executed. Checks: archive size (20 MiB, 80 MiB unpacked, 2,000 entries), tar safety
(no absolute paths, no `..`, no symlinks, hard links or device nodes, no duplicate entries, bounded gzip
output), required manifest fields, hotkey signature over the artifact hash, profile version, allowed and
forbidden paths from the diff, declared licences, exact duplicates and cosmetic duplicates (normalized
diff hash). Rate limit: 10 preflights per hotkey per day. One active submission per hotkey and per
lineage. *Where: `room_protocol.preflight`, `room_api.services.intake`.*

### 2.2 Waiting list and reservation

If no evaluation slot can be reserved the submission joins a free waiting list ordered by signed preflight
time. Invitations last 24 hours; a missed invitation returns the entry to the back of the list. A
reservation holds one slot and produces a signed quote. *Where: `room_api.services.intake`, `control`.*

### 2.3 Quote and payment

A quote binds hotkey, authorized payer, artifact hash, profile and rule hash, recipient wallet, amount in
rao, quote identifier and an expiry in blocks. Accepted quotes never change; new fee levels apply only to
later quotes.

Payment is one atomic call:

```
Utility.batch_all([
  Balances.transfer_keep_alive(dest = evaluation wallet, value = fee),
  System.remark_with_event(remark = "room:quote:<quote id>"),
])
```

A payment counts only when **all** hold: the block is finalized and canonical; `System.ExtrinsicSuccess`
and `Utility.BatchCompleted` are present and `BatchInterrupted` is not; a `Balances.Transfer` event pays
the published wallet at least the quoted amount and matches the call; `System.Remarked` matches the
blake2-256 hash of the remark bytes and the payer; the signer is the authorized payer; the payment
reference (block hash, extrinsic index) has never been used. Verdicts: verified, not finalized (retry
later), late (refund or credit), rejected (with refund when funds actually arrived).
*Where: `room_chain.payment`, `room_api.services.payments`.*

### 2.4 Admission

Admission order is chain order: the finalized payment block number and extrinsic index. The receipt is
signed and issued exactly once, inside the same transaction that consumes the payment and creates the
screening job. *Where: `room_api.services.payments`.*

### 2.5 Screening

A bounded, paid stage in an isolated environment. It may reject only for decisive failures: a build
failure reproduced on a second clean build, no engine start within 15 minutes, crashes or more than 5%
errors, output-contract failures above 5%, peak GPU memory above the ceiling, or smoke accuracy more than
15 points below the champion (a gap at least four standard errors wide on 200 items). **Speed and capacity
are never judged here.** Every rejection publishes a machine-readable error report.

### 2.6 Full evaluation (triage)

Offline quality first; failing it ends the evaluation. Then a capacity search on a published grid, memory
evidence, the short-request control and the multi-turn check with real answers. The result is a triage
estimate against the champion's calibration on the same worker. A submission becomes a *potential winner*
when every gate passes and the triage gain is at least the margin minus a 2-point allowance, so one noisy
estimate cannot reject it without confirmation. *Where: `room_evaluator.pipeline`.*

### 2.7 Confirmation

Promotion evidence is never triage data. It is five fresh **paired blocks**: one re-imaged worker session
each, in which the frozen champion and the challenger are measured on the same newly generated tests, in
an order set by the seed. Blocks are spread across separately provisioned workers, and after the sunset
across independent validators. *Where: `room_api.services.queue`, `room_evaluator.pipeline`.*

## 3. Measurement

### 3.1 Qualified serving capacity

The highest offered request rate (open-loop Poisson arrivals) that is confirmed by runs passing the
per-run gates, with the pooled gates passing across them.

- **Per-run gates:** ≥ 95% of *offered* requests qualified; ≤ 0.5% errored, rejected or past deadline; no
  upward drift in time-to-first-token between the second and last quarter (ignored below the base TTFT
  limit); memory, host RAM and network ceilings respected.
- **Pooled gates:** ≥ 90% qualified in every context band; quality non-inferior; answer length not shorter.
- Every scheduled request counts, including those never started.

### 3.2 Grid and boundaries

Rates are `base × (1 + step)^k` for integer `k` in a finite range. Confirmed capacity: ascend in jumps of
three grid steps, bisect, then confirm three fresh runs at one step below the edge, then further steps down
until a level passes. No pass at the lowest rate ⇒ `below_grid`; a pass at the ceiling ⇒ `at_grid_ceiling`
(conservative). Block capacity is a single-run reading on the same grid, at most six runs per arm.
*Where: `room_evaluator.capacity`.*

### 3.3 Quality (review R1)

Each challenger is compared with the current champion **and** with a frozen quality reference belonging to
the profile version, on the same items, plus absolute per-group floors and an answer-length floor. Small
permitted losses therefore cannot accumulate across generations. Paired comparisons use matched items;
unpaired comparisons are labelled and use the wider interval. *Where: `room_protocol.scoring`.*

### 3.4 Memory evidence (review R7, ADR 0007)

Three kinds of evidence, none of which proves causation:

1. **Tighter budget:** with the cache budget cut by a quarter, the gain must still exceed the replacement
   margin. The full-versus-tight difference is reported.
2. **External accounting:** the resumable idle-conversation capacity must improve by at least the margin.
   Recomputation per qualified request is reported but is never sufficient on its own, because a faster
   stack also recomputes less.
3. **Mechanism review:** a reviewer confirms in the code that the declared mechanism acts on cache
   storage, retention, allocation or admission.

Validation against known methods is part of Stage 1 and is recorded in the readiness report.

### 3.5 Units

P-mem capacity is requests per second. P-live schedules **conversations** per second
(`rps / mean turns`), releases a later turn only after the previous answer completes plus think time, and
counts every remaining turn of a conversation as offered and unqualified when an answer misses its
deadline, so a slow system cannot hide demand.

## 4. Replacement rule

```
G   = C_challenger / C_champion − 1                   (paired blocks, same profile version)
r_b = ln(C_challenger,b / C_champion,b)               (one block b)
L   = mean(r) − t(0.95, n−1) · max(sd(r), σ_floor) / √n
replace only if exp(L) − 1 > δ and every gate, memory evidence, quorum and review pass
```

Initial values: δ = 5%, n = 5 blocks, σ_floor = 0.02, one-sided 95%, grid step 3%. The replication unit is
the block; requests inside a run are not replications. Ties and unclear evidence keep the incumbent. Each
attempt needs a new submission, a new fee and fresh blocks; blocks are never pooled across attempts.
*Where: `room_protocol.scoring.replacement_bound`.*

## 5. Order, leases and settlement (review R2, R3, R4)

- **Dispatch order:** oldest admission key first among compatible queued jobs.
- **Completion order:** free. Workers run different submissions at once.
- **Promotion order:** admission order. A later submission cannot be promoted while *any* earlier paid
  admission is still active, whatever stage it is in. Priority is lost only at a terminal state, and every
  active state is bounded by a published end-to-end deadline, so the barrier always releases.
- **Leases:** 2 h screening, 24 h full evaluation, 8 h per block. An expiry requeues the job once at the
  same admission key; a second expiry ends the submission as an operator failure with a refund or credit.
- **Reservations:** the hard admission cap uses a worst-case envelope per admission (screening, full
  evaluation, worst-case confirmation, one rebase allowance, soak and recalibration: 62.44 GPU-hours with
  the current values), released stage by stage. Average pass rates are used only for forecasts.
- **Promotion:** an atomic check-and-set on the champion pointer. Evidence measured against an older
  champion or rule version is rebased with fresh blocks, keeping the admission key and charging no new fee,
  up to a published maximum.
*Where: `room_protocol.settlement`, `room_protocol.reservation`, `room_api.services.queue`, `settlement`.*

## 6. Champion, weights and registration (review R5, R6)

- One eligible champion per profile receives that profile's whole miner allocation. There are no
  runner-up, maintenance or tie-splitting pools, and the champion never receives owner or validator
  emissions.
- The champion is **the complete stack that was actually tested**, with attribution for the components it
  contains. A later champion may supersede earlier components; the code does not claim that all historical
  patches accumulate.
- Registration is not needed to preflight, queue or pay. It is needed to receive weight: after technical
  approval a winner waits in `ready_for_promotion` until its hotkey is registered, within a published
  grace period. The incumbent keeps earning meanwhile. If the grace ends, the successor expires and the
  incumbent stays.
- Rewards follow the hotkey, resolved to a UID at each weight publication, so a reused UID number never
  redirects a reward.
- With no eligible champion the allocation is proposed for the owner UID, which the chain burns. The
  writer stays disabled until that mechanism is verified on a testnet.
*Where: `room_protocol.weights`, `room_api.services.settlement`.*

## 7. Verification and bootstrap (review R8)

- Workers owned by one validator are **parallel**, not independent. The interface says so.
- Bootstrap: the operator is the only scoring validator; promotion evidence must come from at least two
  separately provisioned workers. This is a trust assumption, not verification.
- After the sunset: at least two scoring validators with different operators, each contributing blocks,
  with committed reports revealed before pooling; a missing validator is omitted rather than counted;
  disagreement beyond the published noise band holds promotion.
- Signatures and commitments prove authorship and integrity, never honest measurement.
- Mainnet readiness keeps the whitepaper's Stage 5 gate: three independent scoring validators, none above
  one third of scoring stake.

## 8. Money

Separate records, each idempotent: fee received, fee consumed, excess credit, credit issued and used,
refund liability, refund sent and confirmed. Fees are consumed once screening or evaluation has run,
whatever the result. Operator or validator failures are never charged, and never require a second payment.
The fee is derived from a published formula over service cost, a recovery share and a price observation
with a maximum age; stale prices refuse new quotes. *Where: `room_protocol.fees`, `room_api.services.accounting`.*

## 9. Randomness and audit

A comparison record naming the champion version, the challenger, the worker and a **future** drand round is
anchored before that round exists; the seed is the hash of the round's randomness and the comparison
identifier. Missing rounds roll forward by a fixed rule; a voided block is published with its reason and
its exposed tests are never reused. Block hashes are not treated as unbiased randomness.

Every consequential transition is appended to a hash-chained audit log that a database trigger protects
from updates, deletes and truncation. The chain makes silent edits detectable; it does not prove that the
recorded decisions were fair.

## 10. Deliberate deviations from the whitepaper

| Rule | Whitepaper v0.2 | Here | Why |
|---|---|---|---|
| Memory evidence | Gain within 2 points of the full-budget gain | Gain must exceed the margin under a 25% smaller budget; the difference is reported | Both are single-run grid readings; rounding alone moves 2 points (ADR 0007) |
| Recomputation | Counts towards memory evidence | Reported only | It also falls for a faster stack (review R7) |
| Confirmation step-downs | 97% then 94% of the edge | Continue stepping down until a level passes three fresh runs | Otherwise a noisy edge yields no capacity at all; the result stays conservative |
| P-live rate | 97% of confirmed capacity | Configurable, 90% initially | Provisional until measured |
