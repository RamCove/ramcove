# ADR 0006 — drand rounds are scheduled ahead; signatures are not verified here

**Status:** accepted with a known gap, 2026-09-17

**Context.** Tests must be unknowable when an artifact is frozen, and nobody may redraw them.

**Decision.** A comparison record naming a future drand round is anchored before that round exists. The
seed is `sha256(round randomness || comparison id)`. Missing rounds roll forward by a fixed rule; a voided
reading is published with its reason and its exposed tests are never reused. The public quicknet parameters
(3-second period, genesis 1692803367) were read from drand's own API on 2026-09-17.

**Launch step.** Rounds are accepted when several relays agree, and disagreement is treated as
unavailable. Verifying drand's BLS signature against the chain's public key is added before the network
deployment.
