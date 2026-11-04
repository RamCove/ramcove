# RamCove protocol, as implemented

Version 0.1 of the implementation, against RamCove whitepaper v0.2 and its review. Every rule below exists in
code; the column "where" names the module that owns it. Provisional values live in an immutable profile
version (`config/profiles/ramcove-p1@1.0.0.json`) whose hash is recorded with every quote, comparison and
promotion.

**Nothing here is measured.** Runtimes, thresholds, capacities and costs are planning values until a Stage 1
study on real hardware replaces them.

## 1. Profile

A profile fixes everything that affects a raw capacity number: model repository and revision, engine
repository, tag and commit, image digests, driver and firmware, the single H100 SXM, the candidate VM
(16 cores, 64 GiB, no swap, no network), context limit, decoding, workloads, gates, the replacement rule,
deadlines, the fee formula and the deployment mode. Different hardware is a different profile; scores never
share a leaderboard. *Where: `ramcove_protocol.rules`.*

## 2. Submission lifecycle

States and the events between them are a single table (`ramcove_protocol.state`). Terminal states never move
again, except that an upheld appeal reopens a rejected review.

```
preflight_passed → waitlisted ⇄ invited → quoted → admitted → screening → eval_queued → evaluating
  → ready_for_promotion → promoted
  (a flagged winner: evaluating → in_review → ready_for_promotion)
  (only if the profile sets reproduce_winners: evaluating → reproduce_queued → reproducing → [in_review →] ready_for_promotion)
```

Exits: `rejected_preflight`, `rejected_screen`, `not_promoted`, `review_rejected`, `expired_quote`,
`expired_unregistered`, `operator_failed`, `withdrawn`.

### 2.1 Free preflight

No candidate code is executed. Checks: archive size (20 MiB, 80 MiB unpacked, 2,000 entries), tar safety
(no absolute paths, no `..`, no symlinks, hard links or device nodes, no duplicate entries, bounded gzip
output), required manifest fields, hotkey signature over the artifact hash, profile version, allowed and
forbidden paths from the diff, declared licences, exact duplicates and cosmetic duplicates (normalized
diff hash). No daily limit. One active submission per hotkey and per
lineage. *Where: `ramcove_protocol.preflight`, `ramcove_api.services.intake`.*

### 2.2 Waiting list and reservation

If no evaluation slot can be reserved the submission joins a free waiting list ordered by signed preflight
time. Invitations last 24 hours; a missed invitation returns the entry to the back of the list. A
reservation holds one slot and produces a signed quote. *Where: `ramcove_api.services.intake`, `control`.*

### 2.3 Quote and payment

A quote binds hotkey, authorized payer, artifact hash, profile and rule hash, recipient wallet, amount in
rao, quote identifier and an expiry in blocks. Accepted quotes never change; new fee levels apply only to
later quotes.

Payment is one atomic call:

```
Utility.batch_all([
  Balances.transfer_keep_alive(dest = evaluation wallet, value = fee),
  System.remark_with_event(remark = "ramcove:quote:<quote id>"),
])
```

A payment counts only when **all** hold: the block is finalized and canonical; `System.ExtrinsicSuccess`
and `Utility.BatchCompleted` are present and `BatchInterrupted` is not; a `Balances.Transfer` event pays
the published wallet at least the quoted amount and matches the call; `System.Remarked` matches the
blake2-256 hash of the remark bytes and the payer; the signer is the authorized payer; the payment
reference (block hash, extrinsic index) has never been used. Verdicts: verified, not finalized (retry
later), late (refund or credit), rejected (with refund when funds actually arrived).
*Where: `ramcove_chain.payment`, `ramcove_api.services.payments`.*

### 2.4 Admission

Admission order is chain order: the finalized payment block number and extrinsic index. The receipt is
signed and issued exactly once, inside the same transaction that consumes the payment and creates the
screening job. *Where: `ramcove_api.services.payments`.*

### 2.5 Screening

A bounded, paid stage in an isolated environment. It may reject only for decisive failures: a build
failure reproduced on a second clean build, no engine start within 5 minutes, crashes or more than 5%
errors, output-contract failures above 5%, peak GPU memory above the ceiling, or smoke accuracy more than
15 points below the champion (a gap at least four standard errors wide on 200 items). **Speed and capacity
are never judged here.** Every rejection publishes a machine-readable error report.

Screening takes about 10 minutes of GPU time and asks the 200 screening questions of the week's question
bank (section 2.8).

### 2.6 The champion's fixed score

When a champion is crowned, each worker measures it once and keeps the result: full-budget capacity (a
search from the champion's known capacity, confirmed by three fresh runs), tighter-budget capacity, and the
short-request (P-ctl) baseline. It is not measured again until the next champion or a new profile version.
It is kept per worker because physical GPUs differ slightly. *Where: `ramcove_evaluator.pipeline.calibrate`,
`ramcove_api.services.queue`.*

### 2.7 One evaluation

Offline quality first (paired against the champion's answers on the same fresh items, and against the frozen
reference); failing it ends the evaluation. Then one **reading** against the fixed score: single runs step up
a 3% grid from that score until one fails, up to the top of the grid; the reading is the highest rate that
passed. The replacement rule (section 4) decides, with a second reading only when the first is close to the
margin. A winner then runs the winner checks once each: pooled band attainment over its passing runs,
memory evidence (a tighter-budget reading that misses the margin gets one more), P-ctl, P-live at 90% of
its capacity, and a 1-hour soak at 90%.

A winner is promoted automatically unless an automatic check flags it: native code in the change,
third-party components, or a check that reports a flag. Only a flagged winner opens a review, and the
review records which criteria were flagged. A profile can set `reproduce_winners`, which has a worker of
another evaluation group repeat the reading once before promotion; it is off by default. *Where: `ramcove_evaluator.pipeline`, `ramcove_api.services.queue`.*

### 2.8 The owner's question bank

The owner platform builds one secret bank per profile every 7 days (from 2026-09-21 00:00 UTC): 200
screening questions, 4,000 quality questions and the traffic scripts of the capacity readings. Each week's
seed is an HMAC of the owner's secret with the profile and the week number. The bank's fingerprint is
recorded in the public audit log a day before the week starts; jobs in the week receive the week's seed,
never the secret; the seed is published when the week ends, so anyone can rebuild the bank and check the
fingerprint. The champion answers each bank once per worker, and every evaluation in the week compares the
challenger's answers with those. Each reading's traffic mixes the bank's scripts with its own beacon seed.
*Where: `ramcove_protocol.bank`, `ramcove_evaluator.bank`, `ramcove_api.services.banks`.*

## 3. Measurement

### 3.1 Qualified serving capacity

The highest offered request rate (open-loop Poisson arrivals) at which runs pass the per-run gates, with
the pooled gates passing across them. For the champion's fixed score it is confirmed by three fresh runs;
for a challenger it is one reading.

- **Per-run gates:** ≥ 95% of *offered* requests qualified; ≤ 0.5% errored, rejected or past deadline; no
  upward drift in time-to-first-token between the second and last quarter (ignored below the base TTFT
  limit); memory, host RAM and network ceilings respected.
- **Pooled gates:** ≥ 90% qualified in every context band; quality non-inferior; answer length not shorter.
- Every scheduled request counts, including those never started.

### 3.2 Grid and boundaries

Rates are `base × (1 + step)^k` for integer `k` in a finite range. Confirmed capacity: ascend in jumps of
three grid steps, bisect, then confirm three fresh runs at one step below the edge, then further steps down
until a level passes. No pass at the lowest rate ⇒ `below_grid`; a pass at the ceiling ⇒ `at_grid_ceiling`
(conservative). A challenger's reading uses the grid built on the champion's fixed score: it starts at
`k = 0` and steps up while each run passes; a failure at `k = 0` means it did not reach the score. It is
not cut short, because a winner's gain may later be set against a newer champion by arithmetic.
*Where: `ramcove_evaluator.capacity`.*

### 3.3 Quality (review R1)

Each challenger is compared with the current champion **and** with a frozen quality reference belonging to
the profile version, on the same items, plus absolute per-group floors and an answer-length floor. Small
permitted losses therefore cannot accumulate across generations. Paired comparisons use matched items;
unpaired comparisons are labelled and use the wider interval. *Where: `ramcove_protocol.scoring`.*

### 3.4 Memory evidence (review R7, ADR 0007)

Three kinds of evidence, none of which proves causation:

1. **Tighter budget:** with the cache budget cut by a quarter, the challenger's reading against the
   champion's fixed score at that budget must still exceed the replacement margin.
2. **External accounting:** the resumable idle-conversation capacity must improve by at least the margin.
   Recomputation per qualified request is reported but is never sufficient on its own, because a faster
   stack also recomputes less.
3. **Declared mechanism:** the manifest declares whether the change acts on cache storage, retention,
   allocation or admission; a reviewer confirms it in the code when the winner is flagged or disputed.

Validation against known methods is part of Stage 1 and is recorded in the readiness report.

### 3.5 Units

P-mem capacity is requests per second. P-live schedules **conversations** per second
(`rps / mean turns`), releases a later turn only after the previous answer completes plus think time, and
counts every remaining turn of a conversation as offered and unqualified when an answer misses its
deadline, so a slow system cannot hide demand.

## 4. Replacement rule

```
G = R_challenger / S_champion − 1        one reading R against the fixed score S on the same worker
G ≤ δ          the champion stays
G ≥ δ_clear    the challenger wins
otherwise      one more reading G₂ with fresh tests; the challenger wins only if (G + G₂) / 2 > δ
a winner must also pass every quality gate and winner check
```

Initial values: δ = 5%, δ_clear = 9%, grid step 3%, grid from −8 to +16 steps. Gains are compared in
integer parts per million, so exactly 5% does not win. Ties keep the incumbent. Each attempt needs a new
submission, a new fee and fresh tests; readings are never pooled across attempts.
*Where: `ramcove_protocol.scoring.replacement_decision`.*

## 5. Order, leases and settlement (review R2, R3, R4)

- **Dispatch order:** oldest admission key first among compatible queued jobs.
- **Completion order:** free. Workers run different submissions at once.
- **Promotion order:** admission order. A later submission cannot be promoted while *any* earlier paid
  admission is still active, whatever stage it is in. Priority is lost only at a terminal state; leases
  bound every running stage, so the barrier always releases.
- **Leases:** 2 h screening, 24 h evaluation, 8 h reproduction. An expiry requeues the job once at the
  same admission key; a second expiry ends the submission as an operator failure with a refund or credit.
- **Reservations:** each paid admission books screening plus the expected work of one evaluation (3.34
  GPU-hours with the current values) until its result is known. Paid admissions stop when booked work
  reaches two weeks at 80% availability; the rest of the time is the reserve for winners' checks, new
  champions' scores, downtime and reruns. The cap limits the queue's length; it is not a submission window,
  and a paid submission in the queue is always evaluated.
- **Promotion:** an atomic check-and-set on the champion pointer. A queued challenger runs against the
  champion that is current when its turn comes. A winner measured against an older champion is re-compared
  by arithmetic, `(1 + G) / (1 + G_new) − 1` for each champion crowned in between: it keeps its place if the
  result still exceeds the margin and ends as not promoted otherwise. Nothing is measured again. Only a rule
  change or a rollback in between runs the evaluation again, at the same key and with no new fee.
*Where: `ramcove_protocol.settlement`, `ramcove_protocol.reservation`, `ramcove_api.services.queue`, `settlement`.*

## 6. Champion, weights and registration (review R5, R6)

- King of the hill (ADR 0011, ADR 0013). Each profile keeps a queue of five kings; King #1 is the current
  champion. A challenger that beats King #1 becomes the new King #1, every king moves down one place, and King
  #5 leaves the queue. Each king below King #1 earns 20% of the profile's miner allocation, and King #1 earns
  the rest, including the share of every empty slot: 100%, then 80/20, 60/20/20, 40/20/20/20 and 20% each as
  the queue fills (`slot_shares`). A king that is suspended, retired,
  excluded or not registered keeps its place and its share burns; a rolled-back king leaves the queue and the
  kings below it move up. Kings never receive owner or validator emissions.
- The champion is **the complete stack that was actually tested**, with attribution for the components it
  contains. A later champion may supersede earlier components; the code does not claim that all historical
  patches accumulate.
- Registration is not needed to preflight, queue or pay. It is needed to receive weight: after technical
  approval a winner waits in `ready_for_promotion` until its hotkey is registered, within a published
  grace period. The incumbent keeps earning meanwhile. If the grace ends, the successor expires and the
  incumbent stays.
- Rewards follow the hotkey, resolved to a UID at each weight publication, so a reused UID number never
  redirects a reward.
- With only the tuned baseline, the whole allocation is proposed for the owner UID, which the chain burns,
  and so is the share of an ineligible or unregistered king. A plan with any burn keeps the writer disabled
  until that mechanism is verified on a testnet; a plan that pays every share to kings does not need it.
*Where: `ramcove_protocol.weights`, `ramcove_api.services.settlement`.*

## 7. Evaluation and weights

- Evaluation is owner-operated. The owner's workers evaluate every submission, and every worker keeps its
  own fixed score of the champion. Workers run by one party are **parallel**, not independent.
- Every tempo the controller signs a weight document from the latest weight plan: the share of the miner
  allocation per hotkey, the burn hotkey, the chain and netuid, and a validity window of two tempos.
  `GET /v1/weights/latest` serves it only to validators: each read is signed with the validator's hotkey
  over `fetch_payload` (hotkey, method, path, timestamp; ±120 s), and the hotkey must hold a validator permit.
  The public site shows the king queue and the plan's status, not the weights by hotkey. *Where:
  `ramcove_protocol.weight_document`, `ramcove_api.services.weight_documents`,
  `ramcove_api.services.validator_access`.*
- Every validator, the owner's included, submits weights with `ramcove-validator`. It checks the signature
  against the owner key pinned per network, the chain, netuid and window, and that the burn goes to the
  subnet owner. It maps hotkeys to UIDs from its own chain read and submits; anything missing or wrong means
  no submission. Validators other than the owner rely on the owner's scores and do not re-run evaluations.
  *Where: `ramcove_validator`.*
- Signatures prove authorship and integrity, never honest measurement. The replay inputs are published so
  the arithmetic can be recomputed by anyone.
- A profile can set `reproduce_winners` to have a worker of another evaluation group repeat a winner's reading
  before promotion; it is off by default.

## 8. Money

Separate records, each idempotent: fee received, fee consumed, excess credit, credit issued and used,
refund liability, refund sent and confirmed. Fees are consumed once screening or evaluation has run,
whatever the result. Operator or validator failures are never charged, and never require a second payment.
The fee is a flat 0.1 TAO per paid submission. A recent price from the published source only adds the
fee's value in US dollars; a stale price never blocks a quote. *Where: `ramcove_protocol.fees`, `ramcove_api.services.accounting`.*

## 9. Randomness and audit

A comparison record naming the champion version, the challenger, the worker and a **future** drand round is
anchored before that round exists; the seed is the hash of the round's randomness and the comparison
identifier. Missing rounds roll forward by a fixed rule; a voided reading is published with its reason and
its exposed tests are never reused. A second reading uses the same round with the suffix `:reading1`. Block hashes are not treated as unbiased randomness.

Every consequential transition is appended to a hash-chained audit log that a database trigger protects
from updates, deletes and truncation. The chain makes silent edits detectable; it does not prove that the
recorded decisions were fair.

## 10. Deliberate deviations from the whitepaper

| Rule | Whitepaper v0.2 | Here | Why |
|---|---|---|---|
| Recomputation | Counts towards memory evidence | Reported only | It also falls for a faster stack (review R7) |
| Fixed-score step-downs | 97% then 94% of the edge | Continue stepping down until a level passes three fresh runs | Otherwise a noisy edge yields no score at all; the result stays conservative |
