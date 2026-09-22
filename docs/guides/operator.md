# Operator guide

The operator publishes the rules, runs intake and the queue, reviews winners and delivers releases. This
guide covers the controls that exist and the ones that deliberately do not.

The website is read-only and has no sign-in. The operator, reviewers and the appeal panel act with
`ramcove-operator`, each signing in with their own key, and the API checks their roles on every call:

```bash
uv run ramcove-operator --key-uri <your key> console
```

## Daily

- Run `ramcove-operator console`: queue health, leases, expired leases waiting for the sweep, overdue
  reviews, open incidents, pending refunds, worker readiness.
- Watch `/status` as your users see it.
- Check that workers are *safe and ready*, not merely online.
- Run `ramcove-operator audit-verify` after any unusual event.

## Controls you have

| Control | Command | Effect | Recorded |
|---|---|---|---|
| Pause or resume paid admissions | `intake pause\|resume --reason …` | No new quotes; paid work continues; the free waiting list still accepts entries | Reason in the audit trail, visible publicly |
| Open and resolve incidents | `incident open …`, `incident resolve <id>` | Shown on the status page and the overview | Audit trail |
| Approve and send refunds | `refund approve <id>`, then `refund execute <id>` | Two steps, both idempotent; sending needs an authorized signer outside this build | Ledger and audit trail |
| Suspend and roll back a champion | `rollback --reason … [--deliberate]` | The suspended version is kept with its evidence; the previous champion's stack becomes current under a new version, workers record its fixed score again, and waiting winners are evaluated again at their admission key with no new fee; weight goes to no winner until a challenger qualifies | Audit trail, marked deliberate or not |
| Run a controller tick (demo) | `ramcove-admin tick` | Advances the simulated chain and settlement once | Audit trail |

## Controls you do not have, on purpose

- You cannot set a champion by hand.
- You cannot edit a measured score.
- You cannot delete evidence; the audit log is append-only and a database trigger enforces it.
- You cannot promote past an earlier active paid admission.

## Rules changes

A profile version is immutable and its hash is recorded with every quote, comparison and promotion. To
change a rule, publish a new version: it applies only to submissions admitted afterwards. Announce
evaluator changes at least seven days ahead and raise the weights version.

## Review

Only a flagged winner is reviewed: native code, third-party components, a failed scan, a disagreement with
the shadow validator, a dispute or a customer's release requirement. Every other winner is promoted
automatically. Review uses published criteria, and the review record marks which criteria were flagged. A
rejection must cite a failed criterion and explain the evidence. Reviewers list open reviews, with the
flags that sent each one, with `ramcove-operator reviews` and decide with
`review <id> approve`, `review <id> reject --failed <criteria> --reasons …` or `review <id> recuse`; the
appeal panel uses `appeals` and `appeal <id> uphold|dismiss --reason …`. Authors never review their own submission; reviewers with a conflict recuse. Appeals are decided
by someone who was not part of the disputed decision, within the published window.

## Money

Fee income, consumed fees, credits and refund liabilities are separate records. The fee is a flat 0.1 TAO
per paid submission; a recent price from the published source only adds its value in US dollars, and a
stale price never blocks a quote. Accepted quotes never change.

## Question bank

The owner platform issues a secret question bank every 7 days: screening questions, quality questions and
traffic scripts. Each week's seed is derived from `RAMCOVE_BANK_SECRET`, which must live only on the
controller host (demo, test and local runs use a labelled stand-in; any other environment issues no bank and
runs no evaluation without it). The controller commits the next bank's fingerprint to the public audit log
a day before its week and publishes the seed once the week ends (`GET /v1/question-banks`). Workers receive
only the current week's seed. Never share the secret, and treat a suspected leak of a week's bank as an
incident: rotate the secret for future weeks and publish what happened.

## What to tell people honestly

During bootstrap you are the only scoring validator, so your measurements decide promotions. Say so, keep
the shadow validator's reports published, and treat the independent-validator gate as a launch requirement,
not an aspiration.
