# ADR 0008 — Demo fixtures carry labelled variants

**Status:** accepted, 2026-09-18

**Context.** The simulated worker can only evaluate trusted repository fixtures. Duplicate detection then
blocks a second demonstration in the same database, because the fixture bytes are identical.

**Decision.** Each fixture has a small number of variants that differ by one labelled line, and all of them
appear in the trusted registry. Demo-only code paths pick the first variant the database has not seen.
Real artifacts get no such help: exact and cosmetic duplicate detection applies to them unchanged, and the
variant helper lives behind the demo-mode check.

**Consequences.** A local demonstration can be repeated without weakening the rule it demonstrates. The
browser suite still resets the dataset first, so it does not depend on how many variants remain.
