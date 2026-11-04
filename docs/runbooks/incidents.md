# Runbook: incidents

## Severity

| Level | Example | First action |
|---|---|---|
| critical | A champion promoted without evidence; artifact leak; admissions out of order | Pause intake, stop the controller, open a public incident |
| major | Workers unavailable; queue stalled | Pause intake, open an incident |
| minor | One worker down; a review overdue | Record it; watch the queue |
| info | Planned maintenance; a known limitation | Publish it so nobody is surprised |

## Sequence

1. **Record first.** `/operator` → Incidents. The public summary must say what a miner should expect.
2. **Stop the bleeding.** Pause admissions with a reason. Admitted work continues; the free waiting list
   still accepts entries.
3. **Preserve evidence.** Do not delete jobs, comparisons or reports. Void a comparison with a published
   reason instead; its exposed tests are never reused.
4. **Protect miners.** Anything caused on our side ends as an operator failure, never as a rejection of the
   miner's code; the miner submits again, free.
5. **Verify the audit chain** before and after any recovery.
6. **Resolve and publish.** Close the incident with what happened, what changed and what was owed.

## Specific playbooks

- **Stuck leases:** the controller sweeps expired leases; one requeue keeps priority, a second ends the
  submission as an operator failure. If the sweep is not running, the count is visible in the console.
- **Chain observation stale:** admissions take their key from the finalized head, so they stall while the
  reader is behind. Do not hand-admit anything; fix the reader.
- **Question bank leaked or missing:** a week's bank reached someone outside the owner's evaluation workers,
  or no bank was issued. Pause admissions, rotate `RAMCOVE_BANK_SECRET` for future weeks, and publish the incident.
- **Disagreeing readings** (only where a profile turns reproduction on): promotion is held. Do not pick a
  side; schedule a third measurement and record the dispute.
