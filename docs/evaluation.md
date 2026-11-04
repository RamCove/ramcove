# How a submission is evaluated

This is the whole path a submission takes, in order, with the number that decides each step. It is the
same path the whitepaper describes in Chapter 5 and the website shows on `/dashboard`; if the three ever
disagree, the code in this repository is the one that runs.

Every number below comes from the published profile (`config/profiles/…json`, served at `/v1/profile`)
and from the evaluator (`packages/evaluator/ramcove_evaluator/`). The values quoted are the ones in the
profile `ramcove-p1-h100sxm-qwen38-27b-fp8@1.0.0` that ships in this repository.

## The shape of it

```
  free checks ──►  queue place   ──► screening ──► question quality ──► capacity reading ──► the rule
   signature          free;            10 min        4,000 questions      8-min runs from        ≤5% lose
   manifest         books 2.41        200 bank       vs the champion      the champion's        ≥9% win
   patch scope       GPU-hours       questions       and a frozen          fixed score,        between: one
   duplicate                          memory          reference           +3% per step        more reading
       │                │                │                │                    │                   │
     no GPU         order fixed      fail: ends      fail: ends, no      stops at the first     winner ──┐
                   by admission                     capacity measured    run that fails                │
                                                                                                       ▼
                                                                                              winner checks
                                                                                       band attainment, memory
                                                                                       evidence, short requests,
                                                                                       real conversations, soak
                                                                                          3.57 GPU-h, from the
                                                                                            published reserve
                                                                                                       │
                                                                                                       ▼
                                                                                                  promotion
                                                                                     automatic unless flagged;
                                                                                      champion code published;
                                                                                    fixed score measured again
```

## Why it is shaped like this

A capacity measurement is noisy, and every attempt spends the owner's GPU time, so the design has to
answer two questions at once: *is this change real?* and *is this measurement trustworthy?*

- **The champion is measured once, not against every challenger.** Measuring both sides for every
  submission would double the GPU bill and add the champion's noise to the challenger's. Instead each
  worker measures the champion once, when it is crowned, and every challenger on that worker is compared
  with that one fixed number. Every worker runs the same frozen profile on the same GPU type, so a
  challenger measured later faces the same conditions.
- **Quality comes before capacity.** A stack that serves more requests by answering them worse is not an
  improvement. Quality is cheap to check and it ends the evaluation before any capacity time is spent.
- **One evaluation decides.** There is no confirmation block and no rebase: a challenger is measured once
  against the fixed score, with a second reading only when the first lands in the undecided band.
- **The expensive checks are only for a winner.** Memory evidence, the short-request control, real
  conversations and the hour-long soak cost more than the evaluation itself. They run only after a winning
  reading, and they come from the published reserve, not from the submission's booking.

## Step by step

### 1. Free checks

Signature, manifest, patch scope, artifact limits, duplicate and lineage. No GPU is used, no registration
is needed and no queue place is taken.

### 2. Queue place — free

Submitting is free: the owner runs the evaluation workers and bears their GPU time. An admission books
**2.41 GPU-hours**: screening (0.17) plus one evaluation (2.24). That booking is what the queue cap is
counted against. **A winner's extra checks are not in it** — they come from the reserve — and neither is
the new champion's re-measurement.

Joining the queue needs a hotkey registered on the subnet; one active submission per hotkey and per
lineage. While the two-week queue is fully booked, a submission waits on the free waiting list and is
invited in order. The finalized block at admission and the order within that block fix the order in which
submissions are tested and promoted.

### 3. Screening — 10 minutes, 0.17 GPU-h

An isolated build, an engine start within 5 minutes, **200 questions** from this week's owner bank
(150 long-context, 50 general) sent as load, and the memory ceiling. Speed is not judged here. A
submission ends here on a build failure, a start failure, a ceiling breach, more than 5% of requests
errored or timed out, more than 5% of answers that break the output contract, or a smoke accuracy more
than 15 points below the champion's — and that last one only when the gap is also four standard errors
wide, because 200 items cannot separate a small difference.

### 4. Question quality — 4,000 questions, 1.00 GPU-h

The challenger answers the whole bank for this period: **3,200 long-context and 800 general** questions.
The long-context items are spread evenly over the four context bands — 800 each — because the rule bounds
accuracy per band, and the widest contexts would otherwise carry too few items to bound anything.
Its answers are compared, question by question, with the champion's answers to the *same* questions
(recorded once per worker per bank) and with a frozen reference implementation.

It must be no worse than the champion by more than 2.00 points overall (3.00 within any one stratum),
no worse than the frozen reference by more than 3.00 points, above the absolute floors (85% overall and
general, 80% per position group), and its answers must stay at least 90% as long as the reference's.
Failing ends the evaluation: no capacity is measured.

The questions themselves come from the owner's bank, not from a validator: a seed derived with HMAC from
the owner's secret, the profile and the 7-day period. The bank's fingerprint is published a day before
its period starts and its seed is revealed once the period ends, so anybody can rebuild the exact
questions afterwards and check the grading.

### 5. Capacity reading — 8-minute runs, 0.36 GPU-h each

A reading starts at the champion's fixed score and steps up **3%** after every run that passes, up to 60%
above the fixed score. Each run is an 8-minute window of open-loop Poisson traffic with two one-minute
bursts, then up to 90 seconds of drain. A run passes when:

- at least **95%** of offered requests are qualified (every scheduled request counts, including those
  rejected, timed out or unfinished);
- at most **0.5%** errored, were rejected or timed out;
- p90 end-to-end time in the last quarter is at most **1.40×** the second quarter's — a queue that keeps
  growing means the rate is past capacity;
- after each of the two one-minute bursts, p90 end-to-end returns to **1.35×** the pre-burst level in the
  quiet stretch that follows. These two are ratios, so they apply only while that p90 is at least **half
  of the requests' own limits**: a stack with memory to spare is so fast before a burst that a harmless
  rise afterwards looks like a large ratio;
- every request answers within its stall limit (no gap over 2 s between output tokens) and comes back
  whole; a truncated answer does not qualify, however fast it was;
- nothing is still in flight when the drain ends;
- peak GPU memory stays under the ceiling.

The reading is the highest rate that passed, and it stops at the first rate that fails. A run is not
retried: one noisy run ends the reading where it is. Three runs is the expected length, which is why an
evaluation is budgeted at 2.24 GPU-hours rather than the 17 runs the grid allows.

### 6. The rule

Gain `G = reading ÷ the champion's fixed score − 1`, in integer parts per million.

| first reading | what happens |
| --- | --- |
| at or below **5%** | not a winner |
| at or above **9%** | winner; go to the winner checks |
| in between | exactly one more reading with fresh traffic; the average of the two must exceed 5% |

Because the comparison is arithmetic against a fixed number, a winner whose promotion is overtaken by a
newer champion can be re-compared without running anything again.

### 7. Winner checks — 3.57 GPU-h, from the reserve

Only a winning reading gets here. Each check answers a question the reading alone cannot:

- **Pooled band attainment (90%)** — the reading could pass overall while failing long contexts. This
  pools every passing run and checks each context band separately.
- **Accuracy under load** — the answers given while the load ran, pooled over the passing runs and the
  soak, against what the champion answered during the three confirmation runs behind its fixed score. An
  answer that never arrived counts as wrong, so dropping the hard questions does not help. The soak is
  what makes this sample large enough to bound: an eight-minute run is not.
- **Memory evidence** — the same reading again at a **25% smaller cache budget** (the profile's 40 GiB
  cache drops to 30; the simulator in this repository works on its own scale of 32 and 24),
  against the champion's fixed score at that budget, plus external accounting of resident idle
  conversations. A gain that disappears when the cache shrinks was not a memory gain. A reading that
  misses the margin gets one more before it fails, because one noisy run must not decide a winner.
- **Short-request control (P-ctl)** — one 10-minute run of short single-turn requests. A stack that wins
  on long conversations by making short ones worse is not an improvement.
- **Real conversations (P-live)** — one 20-minute run at 90% of the measured capacity where each turn is
  built from the model's *actual* previous answer. Slow systems cannot hide demand: every scheduled
  conversation counts from its arrival.
- **Soak** — one hour at 90% of the measured capacity. It is where leaks, fragmentation and slow drift
  show up; a reading is only eight minutes long and cannot see them.

Failing any of them means the submission is not promoted.

### 8. Promotion

Promotion is automatic unless an automatic check flagged the work for a person. Promotions happen in
admission order, not in finishing order. When a champion is crowned, its patches are published (any miner
can fetch them with `ramcove-miner champion-code`) and **every worker measures the new champion's fixed
score again**: a search, three 20-minute confirmation runs, the tighter-budget score, the short-request
baseline and the champion's answers to the current bank — about 6.51 GPU-hours per worker, from the
reserve.

## What the dashboard shows while this runs

A worker reports where it is inside a stage, and `/dashboard` repeats it: `Screening: 100 of 200 smoke
questions answered`, `Question quality: 2,300 of 4,000 answered`, `Capacity reading 1: run 2 at the
champion's score +3.0%`, `Winner check: 60-minute soak at 0.463 req/s`.

This is display only. It is written by the worker holding the lease, it is never an input to any decision,
and losing it changes nothing but the page. The vocabulary is in
`services/api/ramcove_api/services/queue.py` (`PROGRESS_STEPS`) and the wording in
`services/api/ramcove_api/services/public.py` (`progress_label`).

## GPU time, in one table

| Work | GPU-hours | Drawn from |
| --- | --- | --- |
| Screening | 0.17 | the submission's booking |
| One evaluation (quality, check, reading) | 2.24 | the submission's booking |
| **Booked per admission** | **2.41** | the queue's two-week capacity |
| Winner checks | 3.57 | the reserve |
| A new champion's fixed score, per worker | 6.51 | the reserve |

The reserve is 20% of each worker's week, published with the queue. All of it is the owner's GPU time:
miners pay no submission fee.

## Simulation mode and network mode

In simulation mode — what the public demo runs — the GPU workers use `SimulatedStack`, a coarse model of a
memory-bound server, and every number the demo shows comes from it. It exercises the whole protocol and is
not a prediction of H100 behaviour. In network mode the worker's VFIO provider runs the same pipeline on a
whole H100, and the Stage 1 calibration sets the measured values before any of this decides real money.
