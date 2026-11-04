# Validator guide

RamCove separates two jobs.

- **Evaluation, owner-operated.** The owner's evaluation workers run every paid submission on the profile's
  hardware (one whole H100 SXM per worker), check correctness, quality and performance, and decide the king
  queue. Every tempo the owner's controller publishes the outcome as a **signed weight result**.
- **Setting weights, any validator.** Every validator, the owner's included, submits weights from that
  signed result with `ramcove-validator`, a CPU-only program. Validators other than the owner run no H100
  tests: they rely on the owner's published scores rather than checking performance themselves.

## Setting weights with `ramcove-validator`

You need a hotkey registered on the subnet with a validator permit (the chain gives permits to the
validators with the most stake), a machine with a few CPU cores, and network access to the owner's API and
to a Bittensor RPC endpoint. No GPU, no evaluation data and no database.

Each cycle, every 30 seconds by default, the program:

1. Fetches the owner's signed weight result from `GET /v1/weights/latest`.
2. Checks the signature against the owner key **pinned in the program** for this network. It never trusts a
   signer named by the server it fetched from.
3. Checks that the result is for this chain (genesis hash) and this subnet, and still valid at the finalized
   head. A result is valid for two tempos and the owner renews it every tempo.
4. Checks that the unpaid share burns to the subnet owner's hotkey.
5. Maps the hotkeys in the result to UIDs from its own chain read. A hotkey that is not registered has its
   share moved to the burn hotkey.
6. Submits the weights, and resubmits an unchanged result once a tempo so the validator stays active.

If the owner cannot be reached, or any check fails, nothing is submitted and the next cycle tries again. The
program never invents weights of its own.

```bash
# simulation mode: the dev chain runs inside the owner's service, so a development key is enough
uv run ramcove-validator --api http://127.0.0.1:8787 --key-uri //YourDevKey

# network mode: reads the chain directly
uv run ramcove-validator --api https://<owner host>:8788 --chain-endpoint wss://<rpc> --hotkey <your hotkey>
```

In network mode the program reads the chain; submitting the weights on testnet or mainnet is one of the
launch steps in the README. The owner signing keys for testnet and mainnet are pinned in
`ramcove_validator/core.py` when the subnet launches there.

### Without running anything: child hotkeys

Bittensor's `set_children` lets a validator delegate part of its stake weight on one subnet to another
hotkey. A validator that sets the owner's validator hotkey as its child on RamCove's subnet runs nothing at
all: the owner's weights then carry its stake.

## What you are trusting

The signature proves that the result came from the owner and was not altered. It does not prove that the
owner's measurements are right. Everything needed to recompute the arithmetic is published (signed reports,
the hash-chained audit log, the question banks once their week ends), but a validator that sets weights
from the owner's result does not independently verify performance. The king queue and the five 20% shares
are in the result exactly as the owner's evaluation decided them.

## The owner's evaluation workers

This part applies only to the owner. A worker is one physical host with one whole H100 SXM 80 GB: no MIG, no
time-slicing, no other workload during a measurement. The candidate runs in a hardware-virtualized VM with
the GPU passed through, 16 dedicated cores, 64 GiB, no swap and no network. Builds happen in separate,
disposable, network-less VMs. The measurement agent and the queue state live on a trusted controller that
never runs candidate code.

```bash
RAMCOVE_WORKER_ID=w-op-1 \
RAMCOVE_WORKER_KEY_URI="//YourWorkerDevKey" \
RAMCOVE_WORKER_PROVIDER=simulated \
uv run ramcove-worker
```

`RAMCOVE_WORKER_PROVIDER=vfio-vm` selects the real boundary and needs `RAMCOVE_GPU_BDF`,
`RAMCOVE_VM_IMAGE_SHA256` and `RAMCOVE_MEASUREMENT_AGENT_SOCKET`. It refuses to run until every readiness probe
passes, and a refusal is recorded as an infrastructure failure, never charged to a miner. The worker signs
every request with its own key and holds no database credentials, no chain key and no repository token.

**Online is not ready.** *Online* means a heartbeat arrived. *Safe and ready* means the isolation probes
passed. Only a safe-and-ready worker is given work, and a worker without untrusted-code isolation can only
evaluate trusted repository fixtures.

**The champion's fixed score.** When a champion is crowned, each worker measures it once: full-budget
capacity (a search confirmed by three fresh runs), tighter-budget capacity and the short-request baseline.
That fixed score is what every challenger on the worker is compared with, until the next champion or a new
profile version. It is recorded per worker because physical GPUs differ slightly; workers run by one party
are parallel, not independent.

**Questions.** Each job carries the current week's question-bank seed from the owner platform, never the
owner's secret. Every job in the week uses the same screening and quality questions, and each reading's
traffic also mixes in its own beacon seed.

**Readings.** A reading takes a seed from a beacon round fixed in advance and steps the challenger up a 3%
grid from the fixed score until a rate fails. One reading decides; a first reading between the 5% margin and
9% gets one more, and the average of the two decides. A winner then runs the memory, short-request,
multi-turn and soak checks once.

## Costs

Setting weights costs a validator only its machine. The evaluation fee goes to the owner's evaluation
wallet as validation cost recovery, and the owner covers any shortfall in the cost of evaluation.
