# Runbook: backup and recovery

**Status: procedure written, not yet exercised on a real deployment.** Practise it before relying on it.

## What must survive

| Data | Where | Loss means |
|---|---|---|
| Admissions, payments, receipts, champions, ledger, audit | PostgreSQL | you cannot say who paid or who won |
| Artifacts and reports | object store (local directory in this build) | you cannot replay or review |
| Profile versions | database plus `config/profiles/` in git | rules become unverifiable |
| Signing keys | external signer | you cannot issue receipts or weights |

## Backups

- Database: nightly base backup plus continuous WAL archiving. Verify the archive, not just the job exit
  code.
- Artifacts: content-addressed; replicate the bucket and verify a sample by hash.
- Keep at least 35 days, and keep the audit log for as long as the dispute window plus a margin.

## Restore

1. Stop the controller and the workers. Leave the API off. Nothing may write while you restore.
2. Restore the database to the chosen point in time.
3. Restore the artifact store to the same point or later; artifacts are immutable, so extra objects are
   harmless.
4. Verify the audit chain: `GET /v1/operator/audit/verify` must report `ok` and a plausible count.
5. Reconcile the chain cursor: the payment scanner resumes from `payment_scan_cursor`. Re-scanning is safe
   because payment references and receipts are unique.
6. Reconcile money: for every `fee_received` there must be a receipt; for every `refund_sent` a finalized
   transfer. Investigate any mismatch before opening intake.
7. Start the API, then the controller, then workers. Leave intake paused until the checks above pass.

## Data loss window

Anything after the restore point is gone. Payments that were finalized on chain are recoverable: the
scanner re-observes them and issues the receipt exactly once. Work already done by workers is not
recoverable and will be repeated at operator cost, not the miner's.
