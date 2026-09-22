# Miner guide

You submit a code change to a pinned serving engine. RamCove measures how much more qualified work one fixed
GPU serves with your change than with the current champion, in one evaluation. If the gain is enough, you
become the champion and receive that profile's miner allocation until someone beats you.

## Before you write code

Open the rules page (`/docs/rules`). It fixes everything that affects the number: the model repository
and revision, the engine commit, the GPU, the candidate virtual machine, the context limit, the workload
and every gate. Your change must build against that exact engine commit and touch only the allowed paths.

## What a submission contains

A gzip-compressed tar with exactly:

- `manifest.json` — profile, your hotkey, a lineage name, the champion version you built on, a short
  description of the method, its mechanism, your licence and any third-party components.
- `patch.diff` — a unified diff against the pinned engine commit.
- optional `NOTICE` and `LICENSES/…`.

Limits: 20 MiB packed, 80 MiB unpacked, 2,000 entries. Licences must be Apache-2.0, MIT or BSD-3-Clause.

## Submitting

```bash
uv run ramcove-miner pack   --patch patch.diff --manifest manifest.json --out artifact.tar.gz
uv run ramcove-miner submit --artifact artifact.tar.gz --key-uri "//YourDevKey"
```

The command runs the free checks, reserves capacity if any exists, shows the quote, and pays only after you
agree. The website has no sign-in and takes no submissions: everything a miner does happens here, and the
dashboard shows where each submission stands.

You sign two different things, and RamCove never asks for a seed phrase or a key file:

1. **Sign-in and your artifact hash** — proves who you are and what you submitted. Authorizes no payment.
2. **The fee payment** — one atomic transaction: a transfer to the published evaluation wallet plus a note
   carrying the quote identifier, so the payment can only admit that artifact.

## What is free and what costs

Free: format, size, signature, path, licence and duplicate checks, and the waiting list. If the evaluation
queue is full (two weeks of booked work) you are not asked to pay. There are no rounds: submit any time.

Paid: everything after your payment is finalized. The fee is consumed once screening or evaluation has run,
whatever the result — including a rejection caused by your code.

Never charged: operator or validator failures, an expired quote, or withdrawal before any GPU work starts
(that returns a credit). A paid submission in the queue is always evaluated, however long it waits.

If your payment went through but the tool lost track of it, recover it by reference:

```bash
uv run ramcove-miner recover --block <N> --index <I> --key-uri "//YourDevKey"
```

This never charges a second fee.

## How your place in line works

Your position is the block and index of your finalized payment. Workers may evaluate several submissions at
once, so results finish out of order, but promotion still follows admission order: an earlier paid
submission that is still active holds its place until it finishes or its lease runs out twice.

## What happens to your code

1. **Screening** — an isolated build and a short correctness check. It can reject only for decisive
   failures and never judges speed.
2. **Evaluation** — quality first, then one capacity reading against the champion's fixed score: runs step
   up a 3% grid from that score until one fails. The champion is not measured again for you; its score was
   recorded when it was crowned.
3. **Winner checks** — only if you won: memory evidence, a short-request control, a multi-turn check that
   uses the model's real answers, and a soak test, each once.
4. **Review, only if flagged** — native code, third-party components, a failed scan or a dispute send a
   winner to people, who check it against published criteria. Otherwise promotion is automatic.

## How you win

Your gain over the champion's fixed score must exceed the published margin (initially 5%), with every
gate passed. A first reading at 9% or more wins at once; one between 5% and 9% gets one more reading, and
the average of the two must exceed 5%. A near-tie keeps the incumbent. Resubmitting identical code cannot
win; each attempt needs fresh tests and a fresh fee.

If another submission is crowned while you wait in the queue, you are simply evaluated against the new
champion when your turn comes. If you already won and another winner ahead of you is crowned first, your
gain is set against the new champion by arithmetic, (1 + your gain) / (1 + its gain) − 1: nothing is
measured again, you keep your place and you pay no new fee.

## Getting paid

Registration is not needed to submit or queue. It is needed to receive weight: once your submission is
approved you have a published grace period to register the **same** hotkey. The incumbent keeps earning
until you do. Rewards follow your hotkey, never a UID number.

## Why submissions fail

The submission page states the reason in plain words and the documentation page lists every outcome with
what to do next. The most common are: a duplicate, a build failure, offline quality below the fixed
reference, a gain below the margin, or memory evidence that does not hold when the cache budget shrinks.
