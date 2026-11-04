# ADR 0012 — Owner-operated evaluation; validators set weights from signed results

**Status:** accepted, 2026-11-04. Owner decision.

**Context.** The design let every validator run its own evaluation workers, and a shadow validator in a
second independence group repeated each winner's reading before promotion. Evaluating a submission needs a
whole H100 SXM in a hardware VM and the week's question bank, so every evaluating validator would have to rent
that hardware and hold the bank. Two running subnets solve the same problem differently from each other but
alike in one way: in Umi and in Leadpoet only the owner scores, and other validators set weights from the
owner's signed result without evaluating. Leadpoet's 75,000-stake threshold only decides who may take
scoring jobs; where only the owner scores, it has nothing to gate.

**Decision.**
- Only the owner-operated validator evaluates. Its workers run every stage, and its controller builds the
  king queue and the weight plan as before.
- Every tempo the controller signs a weight result (`ramcove.weight_document/1`): the king shares and any
  burn share by hotkey, bound to the network, genesis hash, netuid, plan, rule hash and champion version, and
  valid for two tempos. It is served at `GET /v1/weights/latest` without the proxy key, to validators only
  (ADR 0014).
- Every validator, the owner's included, runs `ramcove-validator` on a CPU machine. Each cycle it fetches the
  result, verifies the signature against the key pinned for that network (never a key the server names),
  checks the network, netuid and validity window, requires the burn hotkey to be the subnet owner, maps
  hotkeys to UIDs (an unregistered king's share goes to the burn), submits, and resubmits once a tempo. It
  fails closed: without a valid result it submits nothing.
- No extra stake threshold. Setting weights needs Bittensor's validator permit, which the chain enforces.
  Validators who prefer to run nothing can delegate to the owner's validator with child hotkeys.
- Reproduction becomes a profile switch, `deployment.reproduce_winners`, off by default. Turning it on needs
  a worker in a second evaluation group. The `bootstrap` block is renamed `deployment`, and the shadow
  validator leaves the demo seed. Mainnet mode no longer forces reproduction, which owner-only evaluation
  could never satisfy.
- Network submission in `ramcove-validator` comes with the release that pins the owner's production signing
  key and submits through commit-reveal; this release submits on the development chain.

**Consequences.** Validators other than the owner need stake and a CPU machine, not an H100, and hold no
question bank. They trust the owner's measurement rather than checking it; what they can check is that the
result is the owner's, current, for this subnet, and consistent with the published king queue, champion
history and audit chain. The owner's measurement is a single point of trust, which the published readings,
the signed audit chain, the review triggers and the appeal process make visible but do not remove. The
profile's rule hash changes, so existing databases are reset.
