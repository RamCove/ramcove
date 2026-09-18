# ADR 0005 — Isolation is a provider interface, and it fails closed

**Status:** accepted, 2026-09-17

**Context.** Miner code is hostile. The prompt and the whitepaper both reject "a container is enough".
No H100 or virtualization backend is available in this environment.

**Decision.** Workers execute stages only through an `IsolationProvider`. `SimulatedTrustedProvider`
evaluates only trusted repository fixtures, identified by normalized patch hash, and declares
`untrusted_code_isolation: false`, so the queue never hands it an unknown artifact and quotes for such
artifacts are refused. `VfioVmProvider` implements the intended boundary's readiness probes (KVM, IOMMU
groups, the GPU bound to `vfio-pci`, a hypervisor binary, a trusted measurement agent socket, a pinned
read-only image, and an explicit unverified check for whether a GPU reset clears memory) and a declarative
VM specification with no network interfaces and an empty environment. When anything is missing it raises
`IsolationUnavailable`, which the queue records as an infrastructure failure and never charges to a miner.

**Consequences.** The honest state of this build is visible in the validator workspace and the status page:
"online" and "safe and ready" are different columns. Real GPU execution stays unimplemented and is reported
as such rather than faked.
