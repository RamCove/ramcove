# ADR 0004 — Payment is `Utility.batch_all(transfer_keep_alive, remark_with_event)`

**Status:** superseded by ADR 0015 (submitting is free; there is no payment). Accepted 2026-09-17.

**Context.** A fee payment must bind to one quote and one artifact, must be atomic, and must be verifiable
from chain data alone.

**Evidence.** Against the deployed runtime (spec 464 on both the test network and Finney): `Utility.batch_all`,
`System.remark_with_event` and `Balances.transfer_keep_alive` exist; `Utility.BatchCompleted`,
`BatchInterrupted`, `ItemCompleted`, `System.Remarked{sender, hash}` and `Balances.Transfer{from, to, amount}`
exist. A real transfer in finalized Finney block 9,088,306 parses with the adapter, and its events correlate
by extrinsic index (`tests/integration/test_chain_readonly.py`).

**Decision.** Require `batch_all`, not `batch`: a plain batch can report success after an inner call fails.
Verify finality, canonical block, outer success, batch completion, the transfer event against the call, the
remark hash against the remark bytes, the authorized payer, and an unused payment reference.

**Unverified.** A `batch_all` payment carrying a remark has not been observed on a live network; the calls
exist in the runtime but the combination is untested there. Testnet must exercise it before real payments.
