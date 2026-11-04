# ADR 0005 — Isolation is a provider interface, and it fails closed

**Status:** accepted, 2026-09-17

**Context.** Miner code is hostile, and a container is not enough of a boundary for it. The same worker
must run in simulation mode and on H100 hosts with hardware virtualization.

**Decision.** Workers execute stages only through an `IsolationProvider`. `SimulatedTrustedProvider`
evaluates only trusted repository fixtures, identified by normalized patch hash, and declares
`untrusted_code_isolation: false`, so the queue never hands it an unknown artifact and such artifacts
wait instead of joining the queue. `VfioVmProvider` implements the intended boundary's readiness probes (KVM, IOMMU
groups, the GPU bound to `vfio-pci`, a hypervisor binary, a trusted measurement agent socket, a pinned
read-only image, and an explicit unverified check for whether a GPU reset clears memory) and a declarative
VM specification with no network interfaces and an empty environment. When anything is missing it raises
`IsolationUnavailable`, which the queue records as an infrastructure failure, never against a miner.

**Consequences.** Each worker's state is visible on the status page, where "online" and "safe and ready"
are different columns. A worker that cannot prove its isolation is never given untrusted code.
