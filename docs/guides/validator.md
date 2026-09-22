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
RAMCOVE_WORKER_ID=w-op-1 \
RAMCOVE_WORKER_KEY_URI="//YourWorkerDevKey" \
RAMCOVE_WORKER_PROVIDER=simulated \
uv run ramcove-worker
```

`RAMCOVE_WORKER_PROVIDER=vfio-vm` selects the real boundary and needs `RAMCOVE_GPU_BDF`,
`RAMCOVE_VM_IMAGE_SHA256` and `RAMCOVE_MEASUREMENT_AGENT_SOCKET`. It refuses to run until every readiness probe
passes, and a refusal is recorded as an infrastructure failure, never charged to a miner.

The worker signs every request with its own key. It holds no database credentials, no chain key and no
repository token.

## Online is not ready

The workspace shows two separate states. *Online* means a heartbeat arrived. *Safe and ready* means the
isolation probes passed. Only a safe-and-ready worker is given work, and a worker without untrusted-code
isolation is never given an unknown artifact — it can only evaluate trusted repository fixtures.

## The champion's fixed score

When a champion is crowned, each worker measures it once: full-budget capacity (a search confirmed by three
fresh runs), tighter-budget capacity and the short-request baseline. The search starts from the champion's
known capacity, so the grid brackets the real value. That fixed score is what every challenger on the worker
is compared with, and it is not measured again until the next champion or a new profile version. It is
recorded per worker because physical GPUs differ slightly.

## Readings and reproduction

A reading takes a seed from a beacon round fixed in advance and steps the challenger up a 3% grid from the
fixed score until a rate fails. One reading decides; a first reading between the 5% margin and 9% gets one
more, and the average of the two decides. A winner then runs the memory, short-request, multi-turn and soak
checks once.

Workers you run yourself are parallel, not independent. During bootstrap the operator's own measurements
decide promotions, which is a trust assumption the interface states. After the sunset, a second validator
with a different operator reproduces each winner's reading on its own worker before promotion, with reports
committed before they are revealed; a validator that misses its window is omitted rather than counted, and
disagreement beyond the published noise band holds the promotion.

## Costs and reimbursement

Reproduction work is reimbursed per run at a published rate. The evaluation fee goes to the operator's
wallet, and the operator, not the miner, pays the gap between one fee and the work of several validators.
This build records the policy and moves no funds.
