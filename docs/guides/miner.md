# Miner guide

You submit a code change to a pinned serving engine. RamCove measures how much more qualified work one fixed
GPU serves with your change than with the current champion, in one evaluation. If the gain is enough, you
become King #1. Each king below King #1 earns 20% of that profile's miner allocation, and King #1 earns the
rest, including the share of every empty slot: the first king earns 100%, and with five kings each earns 20%.
When someone beats King #1 you move down one place, and after five newer kings you leave the queue.

## Before you write code

Open the rules page (`/docs/rules`). It fixes everything that affects the number: the model repository
and revision, the engine commit, the GPU, the candidate virtual machine, the context limit, the workload
and every gate. Your change must touch only the allowed paths.

Build on the current champion, not on the bare engine:

```
uv run ramcove-miner champion-code --out champion/   # the champion's patches, checked against their hashes
```

The champion's code is only its patches, a few kilobytes: apply them in order (`git apply`) to the engine at
the commit shown on the rules page, then make your change on top. RamCove does not host the engine itself.
While version 0 holds the crown there are no patches: the champion is the unmodified engine.

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

The command runs the free checks and then joins the queue, free of charge; if evaluation capacity is fully
booked you join the free waiting list and are invited when it frees. The website has no sign-in and takes no submissions: everything a miner does happens here, and the
dashboard shows where each submission stands.

You sign your sign-in and your artifact hash: that proves who you are and what you submitted, and
authorizes nothing on chain. RamCove never asks for a seed phrase or a key file.

## Submitting is free

There is no submission fee. The owner runs the evaluation workers and bears their GPU time. What limits the
queue is evaluation capacity (two weeks of booked work) and three rules:

- **The free checks** — format, size, signature, path, licence and duplicate checks — need no registration.
- **Joining the queue needs a hotkey registered on the subnet.** Registration is the cost of entry, the
  same hotkey that would receive weight if you win.
- **One active submission per hotkey, and one per lineage name.** There are no rounds and no daily limit:
  submit again as soon as your last submission has finished.

While the queue is full you wait on the free waiting list and are invited in order when capacity frees. A
submission in the queue is always evaluated, however long it waits, and you may withdraw it at any time
before promotion. An infrastructure failure on the owner's side ends it as an operator failure; submit it
again.

## How your place in line works

Your position is the finalized block at which your submission joined the queue and its order within that
block. The submit command prints it, signed by the owner's service. Workers may evaluate several submissions
at once, so results finish out of order, but promotion still follows admission order: an earlier
submission that is still active holds its place until it finishes or its lease runs out twice.

## What happens to your code

1. **Screening** — an isolated build and a 10-minute correctness check with the week's screening
   questions. It can reject only for decisive failures and never judges speed.
2. **Evaluation** — quality first (the week's 4,000 bank questions, the same for every submission that
   week), then one capacity reading against the champion's fixed score: runs step
   up a 3% grid from that score until one fails. The champion is not measured again for you; its score was
   recorded when it was crowned.
3. **Winner checks** — only if you won: memory evidence, a short-request control, a multi-turn check that
   uses the model's real answers, and a 1-hour soak test, each once.
4. **Review, only if flagged** — native code, third-party components, a failed scan or a dispute send a
   winner to people, who check it against published criteria. Otherwise promotion is automatic.

## How you win

Your gain over the champion's fixed score must exceed the published margin (initially 5%), with every
gate passed. A first reading at 9% or more wins at once; one between 5% and 9% gets one more reading, and
the average of the two must exceed 5%. A near-tie keeps the incumbent. Resubmitting identical code is
refused as a duplicate; each attempt needs a changed artifact.

If another submission is crowned while you wait in the queue, you are simply evaluated against the new
champion when your turn comes. If you already won and another winner ahead of you is crowned first, your
gain is set against the new champion by arithmetic, (1 + your gain) / (1 + its gain) − 1: nothing is
measured again and you keep your place.

## Getting paid

Weight follows the hotkey that submitted. If it is no longer registered when your submission is approved,
you have a published grace period to register the **same** hotkey again; the incumbent keeps earning until
you do. Rewards follow your hotkey, never a UID number.

## Why submissions fail

The submission page states the reason in plain words and the documentation page lists every outcome with
what to do next. The most common are: a duplicate, a build failure, offline quality below the fixed
reference, a gain below the margin, or memory evidence that does not hold when the cache budget shrinks.
