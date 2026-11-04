# ADR 0007 — Memory evidence: margin under a tighter budget, not "within 2 points"

**Status:** accepted, 2026-09-18.

**Context.** The first rule required that a challenger's gain under a 25% smaller cache budget stays "within 2
percentage points" of its full-budget gain. Both numbers are single-run readings on a 3% grid, so grid
rounding on each arm can move the comparison by about 6 points on its own. In the simulator this rejected
genuine memory methods at random.

**Decision.** The gate is: under the tighter budget the gain must still exceed the replacement margin, and
the external memory probe (resumable idle-conversation capacity) must improve by at least the margin. The
earlier full-versus-tight comparison is computed and shown as evidence, with the tolerance, but does not
by itself decide. Reduced recomputation is reported and explicitly not sufficient, because a faster stack
also recomputes less.

**Evidence.** Validated against five known methods in the simulator: 8-bit KV and a fragmentation-aware
allocator pass; a retention-only method fails (a false negative); an attention-kernel speedup and a
graph-capture change are correctly rejected. The false negative is kept as a known limitation rather than
tuned away.

**Consequences.** The rule is testable and less noise-sensitive, but it is weaker for a method with a very
large full-budget gain. Calibration on real hardware revisits both the gate and the probe, and may rename
the objective to "capacity under memory pressure" if the diagnostics cannot separate the two causes.

**Update, 2026-09-22.** With one evaluation per submission (ADR 0009) the tighter-budget reading is set
against the champion's fixed tighter-budget score, recorded once when the champion was crowned, and its gain
must exceed the margin; the full-versus-tight difference is no longer computed.
