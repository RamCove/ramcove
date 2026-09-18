# Validator guide

A validator runs evaluation workers and publishes signed reports and weights. This build ships the worker
and the API it talks to; the isolation backend is yours to provide.

## What a worker is

One physical host with one whole H100 SXM 80 GB. No MIG, no time-slicing, no other workload during a
measurement. The candidate runs in a hardware-virtualized VM with the GPU passed through, 16 dedicated
cores, 64 GiB, no swap and no network. Builds happen in separate, disposable, network-less VMs. The
measurement agent and the queue state live on a trusted controller that never runs candidate code.

## Running a worker

```bash
ROOM_WORKER_ID=w-op-1 \
ROOM_WORKER_KEY_URI="//YourWorkerDevKey" \
ROOM_WORKER_PROVIDER=simulated \
uv run room-worker
```

`ROOM_WORKER_PROVIDER=vfio-vm` selects the real boundary and needs `ROOM_GPU_BDF`,
`ROOM_VM_IMAGE_SHA256` and `ROOM_MEASUREMENT_AGENT_SOCKET`. It refuses to run until every readiness probe
passes, and a refusal is recorded as an infrastructure failure, never charged to a miner.

The worker signs every request with its own key. It holds no database credentials, no chain key and no
repository token.

## Online is not ready

The workspace shows two separate states. *Online* means a heartbeat arrived. *Safe and ready* means the
isolation probes passed. Only a safe-and-ready worker is given work, and a worker without untrusted-code
isolation is never given an unknown artifact — it can only evaluate trusted repository fixtures.

## Calibration

Before triage, each worker measures the current champion: full-budget capacity and tighter-budget capacity.
A calibration is valid for a limited period and is invalidated by a champion change, a driver, firmware or
image change, or canary drift. Calibration is used for triage only — never as promotion evidence.

## Blocks and quorum

A confirmation block re-images the worker, takes a seed from a beacon round fixed in advance, and measures
the champion and the challenger on the same tests. Blocks are spread across separately provisioned workers.

Workers you run yourself are parallel, not independent. During bootstrap the operator's own measurements
decide promotions, which is a trust assumption the interface states. After the sunset, promotion needs
blocks from at least two validators with different operators, with reports committed before they are
revealed; a validator that misses its window is omitted rather than counted, and disagreement beyond the
published noise band holds the promotion.

## Costs and reimbursement

Confirmation work is reimbursed per block at a published rate. The evaluation fee goes to the operator's
wallet, and the operator, not the miner, pays the gap between one fee and the work of several validators.
This build records the policy and moves no funds.
