# Operator guide

The operator publishes the rules, runs intake and the queue, reviews winners and delivers releases. This
guide covers the controls that exist and the ones that deliberately do not.

## Daily

- Watch `/operator`: queue health, leases, expired leases waiting for the sweep, overdue reviews, open
  incidents, money records.
- Watch `/status` as your users see it.
- Check that workers are *safe and ready*, not merely online.
- Verify the audit chain from the console after any unusual event.

## Controls you have

| Control | Effect | Recorded |
|---|---|---|
| Pause or resume paid admissions | No new quotes; paid work continues; the free waiting list still accepts entries | Reason in the audit trail, visible publicly |
| Open and resolve incidents | Shown on the status page and the overview | Audit trail |
| Approve and send refunds | Two steps, both idempotent; sending needs an authorized signer outside this build | Ledger and audit trail |
| Suspend and roll back a champion | The suspended version is kept with its evidence; the previous reviewed stack becomes current under a new version, so pending comparisons rebase; weight goes to no winner until a challenger qualifies | Audit trail, marked deliberate or not |
| Run a controller tick (demo) | Advances the simulated chain and settlement once | Audit trail |

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
evidence. Authors never review their own submission; reviewers with a conflict recuse. Appeals are decided
by someone who was not part of the disputed decision, within the published window.

## Money

Fee income, consumed fees, credits and refund liabilities are separate records. The fee is a published
formula over service cost, a recovery share and a price observation with a maximum age; when the price is
stale, new quotes are refused rather than guessed. Accepted quotes never change.

## What to tell people honestly

During bootstrap you are the only scoring validator, so your measurements decide promotions. Say so, keep
the shadow validator's reports published, and treat the independent-validator gate as a launch requirement,
not an aspiration.
