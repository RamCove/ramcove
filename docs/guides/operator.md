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
| Suspend and roll back a champion | `rollback --reason … [--deliberate]` | The suspended version is kept with its evidence; the previous reviewed stack becomes current under a new version, so pending comparisons rebase; weight goes to no winner until a challenger qualifies | Audit trail, marked deliberate or not |
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

Promotion review uses published criteria. A rejection must cite a failed criterion and explain the
evidence. Reviewers list open reviews with `ramcove-operator reviews` and decide with
`review <id> approve`, `review <id> reject --failed <criteria> --reasons …` or `review <id> recuse`; the
appeal panel uses `appeals` and `appeal <id> uphold|dismiss --reason …`. Authors never review their own submission; reviewers with a conflict recuse. Appeals are decided
by someone who was not part of the disputed decision, within the published window.

## Money

Fee income, consumed fees, credits and refund liabilities are separate records. The fee is a published
formula over service cost, a recovery share and a price observation with a maximum age; when the price is
stale, new quotes are refused rather than guessed. Accepted quotes never change.

## What to tell people honestly

During bootstrap you are the only scoring validator, so your measurements decide promotions. Say so, keep
the shadow validator's reports published, and treat the independent-validator gate as a launch requirement,
not an aspiration.
