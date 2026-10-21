
**Conventions that keep the tree traceable.**

1. Every versioned document is `<name>-vN.md`; past versions are never edited, the next number is created instead.
2. ADRs are the exception: numbered once, with a Status line, and superseded by a new ADR rather than versioned.
3. `docs/README.md` lists the latest version of each document, so agents never have to search for it.
4. Every acceptance criterion has a stable ID, never renumbered or reused; tests and code cite it with `@spec`, which is what `trace-check` matches.
5. Status (covered, gap, deferred, drift) lives only in derived files (the test plan and `docs/trace/`), never in a versioned document.

## Appendix A: LID, adopted or not using

| LID element | Status | Where in this framework |
| --- | --- | --- |
| EARS notation for requirements | Adopted | EARS notation for acceptance criteria |
| Stable IDs, never renumbered or reused | Adopted | Conventions 4 |
| `@spec` annotations on tests and code entry points | Adopted | Linking and tracking intent; Conventions 4 |
| Reverse orphan check | Adopted | `trace-check` (blocking) |
| Coverage check: criterion with no citing test | Adopted | `trace-check` (blocking) |
| Staleness tracking | Adopted | `trace-check` (warning) |
| Index of per-segment state (status, last audited commit, drift, next action) | Adopted | `docs/trace/index.yaml` |
| Incremental audit since the last audited commit | Adopted | `verifier` |
| Coverage views regenerated from scans | Adopted | Test plan |
| Intent-narrowing divergence probe | Adopted | `sdd-clarify` (behind a flag) |
| Bidirectional differential audit | Adopted | `sdd-verify` (behind a flag) |
| Zero-context inspector | Adopted | `verifier` |
| Tests before code | Adopted | `sdd-implement` |
| Cascade free within a segment, paused across segments | Adopted | Cascade; size router |
| Bug fixes walk the arrow | Adopted | Cascade |
| `[inferred]` rationale for brownfield code | Adopted | LLD |
| Memory vs intent rule | Adopted | Constitution rules |
| Decision and term placement at the lowest covering node | Adopted | Constitution rules |
| Path-concatenated IDs | Not using | |
| `{node}-specs.md` files beside each design doc | Not using | |
| Status markers (`[x]`, `[ ]`, `[D]`) inside spec documents | Not using | |
| Current-intent documents with history only in git | Not using | |
| Recursive design tree with sub-HLDs | Not using | |
| Per-segment arrow docs | Not using | |
| Decision docs separate from ADRs | Not using | |
| Tenets section in the HLD | Not using | |
| Mandatory stop after every phase | Not using | |
| Advisory-only coherence check | Not using | |
| Atomic rename and re-parent of IDs | Not using | |
| Full and Scoped modes | Not using | |
| Per-model capability flags | Not using | |
| `/map-codebase` brownfield mapping command | Not using | |
| `lid-coach` principle review | Not using | |
