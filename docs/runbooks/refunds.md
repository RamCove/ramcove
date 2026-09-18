# Runbook: refunds and credits

## When a refund or credit is owed

| Situation | Outcome |
|---|---|
| Payment finalized after the quote expired | refund or credit, the miner chooses |
| Underpaid, wrong payer, missing note, plain `batch` | not admitted; refund on request |
| Overpayment | the excess becomes a credit automatically |
| Second payment for a quote already paid | refund liability opened automatically |
| Infrastructure or lease failure, twice | credit issued automatically, submission ends as an operator failure |
| Operator cannot start evaluation within the published window | refund or credit, the miner chooses |
| Withdrawal before any GPU work started | credit |
| Screening or evaluation ran | fee consumed, whatever the result |

## Procedure

1. Find the liability in `/operator` → Money → Refunds. Every row carries the reason and the submission.
2. Approve it. Approval is recorded with your hotkey and is idempotent.
3. Send it. Sending is a separate, idempotent step; in this build it uses the dev chain, and on a real
   network it requires an authorized signer that the API does not hold.
4. Confirmation is automatic once the transfer's block is finalized and its events show success.

## Rules

- Never ask a miner to pay twice for the same admission. Recovery by payment reference exists for this.
- Never silently expire funds. Credits have a published expiry and are shown to the miner with their reason.
- Keep fee income, consumed fees, credits and refund liabilities as separate ledger records; do not net them.
- If you cannot pay a refund within the published window, open an incident and say so publicly.
