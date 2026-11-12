---
title: "M0 plan: foundations and three sources"
type: plan
version: 4
status: approved
approved_by: "Kenny Hill (Engineering)"
approved: 2026-10-23
owner: "Kenny Hill"
milestone: M0
artifact_type: plan
components: [cache, health, platform, search, security, sources]
scope_level: L3
scope_name: "research-mcp"
derives_from: docs/spec/SPEC-v5.md
date: 2026-10-23
supersedes: docs/build/M0-plan-v3.md
---

# M0 plan (v4)

Milestone M0 is the ECC pilot: the platform, identifiers, three sources and the first MCP tools. This version replans [M0 plan v1](M0-plan-v1.md) against the approved Gate 3 documents (the v2 LLDs of platform, security, sources, search, cache and health) and [SPEC-v5](../spec/SPEC-v5.md) (approved 2026-10-23). M0's scope is the set of criteria that the component PRDs mark M0 (SPEC-v5 section 14). `tools/gen_m0_plan.py` builds `.orchestration/plan-m0.json` from the task table below; the columns are unchanged.

Changes from v3 (the architect's plan check in run `rm-m0e`, 2026-10-23, returned `changes_requested`):

- M0-06 depends on M0-19, and M0-19 names the setting `logging.debug` that M0-06 reads (LLD-platform-v2 §4.3, §7.1).
- Section 2.2 adds M0-13: in M0 the federation service records searches through an injected port whose default does nothing. The `searches` row and `StateStore.search_put` belong to SRCH-34, which PRD-search-v3 marks M1.
- Section 2.2 for M0-09 keeps the LLD's `health` port (`Callable[[str], str | None]`, default `None`); `retry_after_ms` stays `None` in M0.
- Section 2.2 for M0-15 says M0-22 may fix `shim.py` if its tests find a defect; its scope keeps the file.

Changes from v2 (the architect's plan check in run `rm-m0d`, 2026-10-23, returned `changes_requested`):

- `tools/gen_m0_plan.py` leaves `done` tasks out of the generated plan and drops dependencies on them, because their code is already on `main` and ECC has no way to mark a unit as merged before a run. A run therefore starts at slice 4.
- M0-15's integration tests move to `tests/integration/` (LLD-platform-v2 §9, decision 13), which also ends its overlap with M0-22 on `tests/unit/test_shim.py`. M0-15 takes `tests/integration/test_reload.py` (LLD-platform-v2 §9: the `SIGHUP` handler and "Reload credentials" for SEC-4), names SEC-4 and depends on M0-20.
- M0-09 depends on M0-17 and M0-18, and M0-13 on M0-17, M0-18 and M0-19, so `depends_on` alone orders them after the follow-ups whose contracts they use.
- M0-19 adds the settings keys `federation.fuzzy_merge` and `federation.record_searches` (LLD-search-v2 §7.2), which M0-13 reads and cannot add itself.
- M0-16 takes `services/doctor.py` (LLD-health-v2 §5.9 and decision 11).
- M0-23 may fix what its test finds in `cli.py`, `daemon.py` and `platform/secrets.py`; it runs alone in the last slice, so the wider scope overlaps no other unit.
- Section 2.2 adds requirements for M0-09 (the `skipped_unhealthy` state for `rate_limited` sources, and the `health(id)` port) and M0-15 (the shim reads the token only from the Keychain from the start).

Changes from v1:

- Every task's Implements column points at the v2 LLDs and SPEC-v5 sections.
- M0-01 to M0-05 were merged in the first run (`rm-m0b`). A task keeps `done` only for criteria whose behavior is unchanged by the Gate 1 to Gate 3 changes. The criteria that changed moved out of M0-04 and M0-05 into the follow-up tasks M0-19 and M0-20; M0-17 and M0-18 are follow-ups to M0-02 and M0-03.
- New tasks cover the M0 criteria that had no task: SRCH-38 (M0-17), SRCH-37 (M0-21), SEC-26 (M0-22) and SEC-24 (M0-23). SEC-30 is named in M0-16.
- The waves are renumbered (11 waves became 12) because M0-06 now waits for the secrets follow-up.

## 1. Slices

> **Owner:** A · **Persona:** `planner`

Each wave is a slice; units in one wave have no overlapping files and can run in parallel.

| Slice | Units | Checkpoint |
| --- | --- | --- |
| 1 | M0-01 | merged in `rm-m0b` (`done`; not in the generated plan) |
| 2 | M0-02, M0-04 | merged in `rm-m0b` (`done`; not in the generated plan) |
| 3 | M0-03, M0-05 | merged in `rm-m0b` (`done`; not in the generated plan) |
| 4 | M0-08, M0-17, M0-18, M0-19, M0-20 | every unit merged with its criteria passing |
| 5 | M0-06 | every unit merged with its criteria passing |
| 6 | M0-07 | every unit merged with its criteria passing |
| 7 | M0-09 | every unit merged with its criteria passing |
| 8 | M0-10, M0-11, M0-12, M0-13 | every unit merged with its criteria passing |
| 9 | M0-14, M0-21 | every unit merged with its criteria passing |
| 10 | M0-15 | every unit merged with its criteria passing |
| 11 | M0-16, M0-22 | every unit merged with its criteria passing |
| 12 | M0-23 | every unit merged with its criteria passing |

## 2. Tasks

> **Owner:** A · **Persona:** `planner`

Columns after Persona are read by `tools/gen_m0_plan.py`: the LLDs the unit implements, its file scope (paths under `src/research_mcp/` unless they start with `src/`, `tests/`, `tools/`, `docs/` or `.github/`; `fixtures/*` stands for the seven fixtures of the sources LLD), the risk that sets its routing tier, and its status. trace-check reads the Status column: only the criteria in the cells of a `done` task are due.

| # | Task | Criteria | Depends on | Persona | Implements | Files (scope) | Risk | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| M0-01 | Repository scaffold, packages and CI script | PLAT-1, PLAT-2, PLAT-3, PLAT-5, PLAT-4 | none | `implementer` | `docs/lld/LLD-platform-v2.md` (§5.1, §5.8, §9; SPEC-v5 6, 12, 15, 17) | `pyproject.toml`, `uv.lock`, `.python-version`, `src/research_mcp/__init__.py`, `src/research_mcp/version.py`, `src/research_mcp/core/__init__.py`, `src/research_mcp/platform/__init__.py`, `src/research_mcp/sources/__init__.py`, `src/research_mcp/services/__init__.py`, `src/research_mcp/mcp_app/__init__.py`, `src/research_mcp/ui/__init__.py`, `src/research_mcp/testing/__init__.py`, `tools/ci.sh`, `.github/workflows/ci.yml`, `tests/conftest.py`, `tests/unit/test_version.py`, `tests/unit/test_import_side_effects.py`, `tests/unit/test_network_guard.py`, `src/research_mcp/packaging/__init__.py` | high | done |
| M0-02 | Identifier normalization | SRCH-10, SRCH-11, SRCH-12, SRCH-13, SRCH-14, SRCH-15, SRCH-16 | M0-01 | `implementer` | `docs/lld/LLD-search-v2.md` (§5.2; SPEC-v5 5) | `core/ids.py`, `tests/unit/core/test_ids.py` | medium | done |
| M0-03 | Specs, models, errors, envelope, budget and test clock | PLAT-30, PLAT-31, PLAT-32, PLAT-33, PLAT-6, PLAT-34 | M0-02 | `implementer` | `docs/lld/LLD-platform-v2.md` (§2.1, §2.2, §5.6); `docs/lld/LLD-sources-v2.md` (§2.2, §3.1); SPEC-v5 3, 4, 5 | `core/specs.py`, `core/models.py`, `core/errors.py`, `core/context.py`, `core/envelope.py`, `core/budget.py`, `core/timeutil.py`, `testing/clock.py`, `tests/unit/core/test_envelope.py`, `tests/unit/core/test_budget.py`, `tests/unit/core/test_models.py` | medium | done |
| M0-04 | Settings and paths (the unchanged criteria) | PLAT-9, PLAT-10 | M0-01 | `implementer` | `docs/lld/LLD-platform-v2.md` (§7.1); `docs/lld/LLD-cache-v2.md` (§3.6); SPEC-v5 4, 9, 10 | `settings.py`, `tests/unit/test_settings.py` | medium | done |
| M0-05 | Secrets and Keychain provider (the unchanged criterion) | SEC-13 | M0-04 | `implementer` | `docs/lld/LLD-platform-v2.md` (§4.1); `docs/lld/LLD-security-v2.md` (§4.3); SPEC-v5 9 | `platform/secrets.py`, `tests/unit/platform/test_secrets.py` | high | done |
| M0-06 | Redaction and structured logging | SEC-5, SEC-6, SEC-14, SEC-7, PLAT-40, PLAT-41, PLAT-42 | M0-03, M0-05, M0-19, M0-20 | `implementer` | `docs/lld/LLD-platform-v2.md` (§4.3, §5.10, §8); `docs/lld/LLD-security-v2.md` (§5.4); SPEC-v5 9, 10, 12 | `platform/redact.py`, `platform/logging.py`, `tests/unit/platform/test_redact.py`, `tests/unit/platform/test_logging.py`, `tests/security/test_no_secret_in_logs.py` | high | done |
| M0-07 | Async HTTP client, rate limits and downloader | PLAT-35, PLAT-36, PLAT-37, PLAT-38, PLAT-39, PLAT-11, SEC-8, SEC-9, SEC-10, CACHE-1, CACHE-2 | M0-03, M0-06, M0-19 | `implementer` | `docs/lld/LLD-platform-v2.md` (§4.4, §5.3, §5.4, §6.1); `docs/lld/LLD-cache-v2.md` (§5.13); `docs/lld/LLD-security-v2.md` (§4.3); SPEC-v5 3, 6, 9 | `platform/http.py`, `platform/download.py`, `platform/ratelimit.py`, `tests/unit/platform/test_http.py`, `tests/unit/platform/test_ratelimit.py`, `tests/unit/platform/test_downloader.py`, `tests/security/test_scoped_credentials.py` | high | done |
| M0-08 | Stores and migrations | PLAT-50, PLAT-51, PLAT-52, PLAT-53 | M0-03 | `implementer` | `docs/lld/LLD-platform-v2.md` (§3.1); `docs/lld/LLD-cache-v2.md` (§3.1, §3.3, §3.4); `docs/lld/LLD-health-v2.md` (§3); SPEC-v5 10 | `platform/stores.py`, `platform/migrations/state/0001_init.sql`, `platform/migrations/cache/0001_init.sql`, `tests/unit/platform/test_stores.py` | high | done |
| M0-09 | Source contract, registry and conformance suite | SRC-1, SRC-2, SRC-3, SRC-4, SRC-5, SRC-6, SRC-7 | M0-02, M0-07, M0-17, M0-18 | `implementer` | `docs/lld/LLD-sources-v2.md` (§2.1, §2.3, §5.1, §5.2, §5.3; SPEC-v5 4) | `sources/base.py`, `sources/registry.py`, `testing/adapters.py`, `tests/sources/conftest.py`, `tests/sources/test_conformance.py`, `tests/unit/sources/test_registry.py`, `tests/unit/sources/test_adapter_imports.py` | high | done |
| M0-10 | arXiv adapter | SRC-10 | M0-09 | `implementer` | `docs/lld/LLD-sources-v2.md` (§3.4, §5.1, §5.3; SPEC-v5 4) | `sources/arxiv.py`, `tests/sources/arxiv/fixtures/*`, `tests/sources/arxiv/test_arxiv.py` | medium | done |
| M0-11 | Crossref adapter | SRC-11 | M0-09 | `implementer` | `docs/lld/LLD-sources-v2.md` (§3.4, §5.1, §5.3; SPEC-v5 4) | `sources/crossref.py`, `tests/sources/crossref/fixtures/*`, `tests/sources/crossref/test_crossref.py` | medium | done |
| M0-12 | OpenAlex adapter | SRC-12 | M0-09 | `implementer` | `docs/lld/LLD-sources-v2.md` (§3.4, §5.1, §5.3; SPEC-v5 4) | `sources/openalex.py`, `tests/sources/openalex/fixtures/*`, `tests/sources/openalex/test_openalex.py` | medium | done |
| M0-13 | Grouping, merge and federation service | SRCH-1, SRCH-2, SRCH-3, SRCH-4, SRCH-5, SRCH-6, SRCH-7, SRCH-8, SRCH-9, SRCH-17 | M0-09, M0-17, M0-18, M0-19 | `implementer` | `docs/lld/LLD-search-v2.md` (§5.3, §5.4; SPEC-v5 5, 11.1) | `services/federation.py`, `services/works.py`, `tests/services/test_federation.py`, `tests/services/test_works.py` | high | done |
| M0-14 | MCP app: M0 tools, the sources resource and `@tool_boundary` | SRCH-20, SRCH-21, SRCH-22, SRCH-23, SRC-8, PLAT-60, PLAT-61, PLAT-62, PLAT-63 | M0-08, M0-13 | `implementer` | `docs/lld/LLD-platform-v2.md` (§2.3, §5.6); `docs/lld/LLD-search-v2.md` (§2.1); `docs/lld/LLD-sources-v2.md` (§2.4); SPEC-v5 5, 9 | `mcp_app/server.py`, `mcp_app/tools_discovery.py`, `mcp_app/resources.py`, `tests/contract/conftest.py`, `tests/contract/test_tools_discovery.py`, `tests/contract/test_tool_contract.py` | high | done |
| M0-15 | Daemon, composition root, scheduler and stdio shim | PLAT-70, SEC-11, SEC-12, PLAT-71, PLAT-72, PLAT-73, PLAT-74, PLAT-75, PLAT-76, PLAT-77, SEC-4 | M0-05, M0-14, M0-19, M0-20 | `implementer` | `docs/lld/LLD-platform-v2.md` (§4.5, §5.2, §5.5, §5.7, §5.10); `docs/lld/LLD-health-v2.md` (§2.1, §5.10); `docs/lld/LLD-security-v2.md` (§5.2); SPEC-v5 2, 3, 9 | `app.py`, `daemon.py`, `shim.py`, `platform/auth.py`, `platform/jobs.py`, `platform/scheduler.py`, `testing/launchctl.py`, `tests/integration/test_app.py`, `tests/integration/test_shim.py`, `tests/integration/test_jobs.py`, `tests/integration/test_scheduler.py`, `tests/integration/test_reload.py`, `tests/security/test_loopback_auth.py` | high | done |
| M0-16 | CLI, install, doctor skeleton and launchd templates | PLAT-80, PLAT-81, PLAT-82, PLAT-83, SEC-30, SRC-13, HLTH-40 | M0-10, M0-11, M0-12, M0-15 | `implementer` | `docs/lld/LLD-health-v2.md` (§2.3, §5.9); `docs/lld/LLD-platform-v2.md` (§2.4, §2.5, §5.8, §5.9); `docs/lld/LLD-security-v2.md` (§5.2); `docs/lld/LLD-sources-v2.md` (§5.10); SPEC-v5 12 | `cli.py`, `services/doctor.py`, `packaging/launchd/local.research-mcpd.plist.template`, `packaging/launchd/local.research-mcp-doctor.plist.template`, `packaging/launchd/local.research-mcp-watchdog.plist.template` (all under src/research_mcp), `tools/gen_inventory.py`, `docs/generated/sources.md`, `tests/unit/test_cli.py`, `tests/unit/test_install.py` | medium | done |
| M0-17 | Follow-up to M0-02: URL trailing-slash rule | SRCH-38 | M0-02 | `implementer` | `docs/lld/LLD-search-v2.md` (§5.2, §12; SPEC-v5 5) | `core/ids.py`, `tests/unit/core/test_ids.py` | low | done |
| M0-18 | Follow-up to M0-03: source states `budget_exhausted` and `not_needed` in the envelope | PLAT-30 | M0-03 | `implementer` | `docs/lld/LLD-platform-v2.md` (§2.1); `docs/lld/LLD-search-v2.md` (§12; SPEC-v5 5) | `core/envelope.py`, `tests/unit/core/test_envelope.py` | low | done |
| M0-19 | Follow-up to M0-04: placeholder email rule, `env:` rejection for `server.token`, new setting defaults (including `logging.debug`), and the search keys `federation.fuzzy_merge` and `federation.record_searches` | PLAT-8, PLAT-11, PLAT-12 | M0-04, M0-05 | `implementer` | `docs/lld/LLD-platform-v2.md` (§4.1, §4.3, §7.1, §9); `docs/lld/LLD-search-v2.md` (§7.2); SPEC-v5 4, 9, 10 | `settings.py`, `tests/unit/test_settings.py` | medium | done |
| M0-20 | Follow-up to M0-05: secret type, Keychain provider and cache reload as redesigned | SEC-1, SEC-2, SEC-3, SEC-4, PLAT-12 | M0-05 | `implementer` | `docs/lld/LLD-platform-v2.md` (§4.1, §5.10, §9); `docs/lld/LLD-security-v2.md` (§4.3); `docs/lld/LLD-health-v2.md` (§5.2); SPEC-v5 9 | `platform/secrets.py`, `tests/unit/platform/test_secrets.py` | high | done |
| M0-21 | Federation: `auto` skips rate-limited sources and reports their status | SRCH-37 | M0-13 | `implementer` | `docs/lld/LLD-search-v2.md` (§5.4; SPEC-v5 5, 11.1); `docs/lld/LLD-health-v2.md` (§5.5) | `services/federation.py`, `tests/services/test_federation.py` | medium | done |
| M0-22 | Shim reads the daemon token only from the Keychain | SEC-26 | M0-15 | `implementer` | `docs/lld/LLD-platform-v2.md` (§4.5, §5.7); `docs/lld/LLD-security-v2.md` (§4.3, §5.2); SPEC-v5 2, 9 | `shim.py`, `tests/unit/test_shim.py` | high | done |
| M0-23 | No registered secret at rest after install, daemon start and reload | SEC-24 | M0-16, M0-19, M0-20, M0-22 | `implementer` | `docs/lld/LLD-security-v2.md` (§3, §4.4); `docs/lld/LLD-platform-v2.md` (§4.1, §4.7, §5.9, §5.10); SPEC-v5 9, 10 | `tests/security/test_no_secret_at_rest.py`, `cli.py`, `daemon.py`, `platform/secrets.py` | high | done |

### 2.1 Notes

- **Package scaffolding.** M0-01 declares every dependency, extra and pytest setting in the platform LLD (§5.8), and creates every package `__init__.py`. No later unit edits `pyproject.toml`, `uv.lock` or an `__init__.py`.
- **No test packages.** Test folders have no `__init__.py`; pytest runs in importlib mode.
- **Parallel units.** Scopes do not overlap within a wave. Units that touch a file of an earlier unit (M0-17 to M0-23) run in a later wave than that unit.
- **Source discovery.** The registry finds adapters, so adapter units touch no shared file.
- **Fixtures.** In the scope column, `fixtures/*` stands for the seven fixtures in the sources LLD (§3.4). The generated plan lists them by name.
- **Done tasks and changed criteria.** M0-04 keeps PLAT-9 and PLAT-10 (unchanged) and M0-05 keeps SEC-13. PLAT-8, PLAT-11 and PLAT-12 changed (placeholder email rule, `env:` rejection for `server.token`, new setting defaults) and SEC-1 to SEC-4 changed; they are in the follow-ups M0-19 and M0-20 and become due when those tasks are done. Assumption: the owner's list of changed criteria is complete; I did not diff the v1 and v2 LLDs line by line. Their existing tests stay in the repository meanwhile. M0-18 and M0-17 are follow-ups for code divergences recorded in LLD-search-v2 §12; M0-18 names PLAT-30 only to put the envelope change under a task.
- **PLAT-11 in two tasks.** M0-19 owns the settings test; the user-agent-without-contact test belongs to M0-07 (LLD-platform-v2 §5.3), so M0-07 names PLAT-11 too.
- **Coverage of the M0 criteria** (component PRDs: platform v4, sources v5, search v3, cache v4, health v4, security v3). Every criterion the PRDs mark M0 is now named by a task, including SEC-30 (M0-16), SEC-24 (M0-23), SEC-26 (M0-22), SRCH-37 (M0-21) and SRCH-38 (M0-17). The only M0 criteria of cache v4 are CACHE-1 and CACHE-2, and the only one of health v4 is HLTH-40. Not M0 by the PRDs: SEC-28 (M2), SEC-29, SEC-31 and SEC-32 (M3), PLAT-13 (M1), PLAT-84 (M2).
- **Gaps, listed explicitly.** (1) PLAT-84 has no task: PRD-platform v4, test plan v4 and LLD-platform-v2 §9 all mark it M2, and its test needs the cache upload state, so it was not added; see Open questions. (2) PLAT-3 is taken as M0 from v1 (its PRD row was too long to read in this pass; assumption). (3) The test names for SEC-30 and for SRCH-1 to SRCH-9 are still proposed in the LLDs.
- **Done tasks in a run.** `tools/gen_m0_plan.py` emits only tasks whose status is not `done` and removes `done` tasks from `depends_on`. A run created from the generated plan starts at slice 4 with 18 units.
- **Ordering by `depends_on`.** Every unit that uses a follow-up's contract names that follow-up: M0-09 and M0-13 depend on M0-17 (URL normalization) and M0-18 (source states); M0-13 depends on M0-19 (the two federation settings keys); M0-15 depends on M0-20 (`SecretCache.reload`). M0-14 and M0-21 reach M0-18 through M0-13.
- **Not edited here.** SPEC-v5 sections 14 and 17 link v1 of this plan. LLD-sources-v2 §5.2 selection row 8 still gives a `rate_limited` source the state `rate_limited`; section 2.2 (M0-09) records the rule M0 builds, and the LLD needs the same correction.

### 2.2 Clarifications from the first M0 attempt and the plan check

The M0-01 to M0-05 rows are carried from SPEC-v2 section 0.6, with the v2 LLD sections that now hold them (SPEC-v5 section 19). The M0-09 and M0-15 rows come from the architect's plan checks in runs `rm-m0d` and `rm-m0e`, and the M0-13 row from `rm-m0e`. They are requirements for the unit named; the LLDs repeat them where they belong, except where a row says an LLD still needs the correction.

| Unit | Source | Requirement |
| --- | --- | --- |
| M0-01 | 1, 12.1; PLAT-5, NFR-9 | The offline network guard MUST be installed for the whole test session (a session-scoped autouse fixture or a plugin active before collection), not per test. It MUST refuse, before any I/O, `socket.socket.connect`, `connect_ex`, `sendto`, `sendmsg` and `socket.create_connection` to non-loopback addresses, and `getaddrinfo`, `gethostbyname`, `gethostbyname_ex` and `gethostbyaddr` for non-loopback names. Loopback MUST keep working. Negative tests MUST prove each refusal happens before I/O. (LLD-platform-v2 §9) |
| M0-01 | 1; PLAT-3 | Import side effects MUST be attributed to `research_mcp` when any frame of the stack belongs to it, not only the innermost frame; a dependency doing I/O on behalf of a `research_mcp` import (for example settings construction reading the environment at import time) counts. Include that case as a regression test. (LLD-platform-v2 §5.1) |
| M0-01 | 12.1; PLAT-FR-53 | The CI workflow MUST run on macOS and Linux with Python 3.12 and 3.13, pin every action by commit SHA, scan for secrets, and run a weekly dependency audit. (LLD-platform-v2 §5.8; LLD-security-v2 §4.3) |
| M0-02 | 6; SRCH-10, SRCH-15 | Every normalizer MUST be idempotent (for example a repository name ending `.git.git` normalizes once to its final form). Percent-decoding MUST be strict UTF-8; invalid sequences raise `IdentifierError` instead of becoming replacement characters. DOI suffixes keep their slashes; handle suffixes MAY contain slashes, and a trailing slash is significant where the LLD says so. (LLD-search-v2 §5.2) |
| M0-03 | 3.7, 4; PLAT-31, SRCH-FR-4 | `Budget.fit` MUST keep `FederatedResult.statuses` (one status per source) and MUST fail explicitly when mandatory metadata cannot fit. Its prefix search MUST distinguish "does not validate" from "too large". (LLD-platform-v2 §5.6; LLD-sources-v2 §3.1; LLD-search-v2 §6) |
| M0-04 | 2; PLAT-8, PLAT-9 | Paths MUST be normalized (resolving `..`) before the durable-location check. Credential names MUST keep their canonical case across TOML and `RESEARCH_MCP_` environment overrides, so an environment override updates the same credential the TOML defines. (LLD-platform-v2 §7.1; LLD-cache-v2 §3.6) |
| M0-05 | 3.1; PLAT-12, SEC-13 | `SecretRef` MUST validate on construction: the name matches the allowed pattern, and a Keychain reference's service is exactly `research-mcp/<NAME>`. No control character (in particular a newline) may reach the `security -i` script. `FakeProvider.metadata` MUST behave like `KeychainProvider.metadata` (no metadata for `env:` references). (LLD-platform-v2 §4.1; LLD-security-v2 §5.1; LLD-health-v2 §5.2) |
| M0-09 | plan check `rm-m0d`; SRCH-FR-8, SRCH-37 | Under `auto`, `registry.select` MUST give a source whose health is `rate_limited` or `down` the skip state `skipped_unhealthy`, with `retry_after_ms` left `None` in M0 (the `health` port carries no time); `budget_exhausted` keeps its own state. PRD-search-v3 SRCH-FR-8 and LLD-search-v2 §5.4 win over LLD-sources-v2 §5.2 row 8. M0-21 only adds the SRCH-37 test and the federation reporting, and does not change `registry.py`. (LLD-search-v2 §2.2, §5.4; LLD-health-v2 §5.5) |
| M0-09 | plan check `rm-m0d` | The registry MUST take health through the LLD's port `health: Callable[[str], str | None]` with the default `lambda s: None` (no health state, so no skip), so M0-21 can test SRCH-37 with a fake; the health service is M1. (LLD-sources-v2 §5.2) |
| M0-15 | plan check `rm-m0d`; SEC-26 | The shim MUST read the daemon token only from the Keychain from the start, and re-read it once on a 401 before failing with `auth_failed`. M0-22 then adds the SEC-26 test and the 401 retry test in `tests/unit/test_shim.py`, and changes `shim.py` only to fix a defect those tests find. (LLD-platform-v2 §4.7, §5.7) |
| M0-13 | plan check `rm-m0e`; SRCH-FR-9 | `FederationService` MUST take search recording as an injected port (for example `record_search`) whose default does nothing, and call it when `federation.record_searches` is on. M0 writes no `searches` row and adds no `StateStore.search_put`; SRCH-34 (M1) wires the port to the store. (LLD-search-v2 §5.4 step 5, §5.11) |

## 3. Verification

> **Owner:** A · **Persona:** `planner`

At the end of each slice the `verifier` checks that every merged unit's criteria have passing tests that cite them, that the behavior entry points carry `@spec`, and that `node tools/sdd/cli.mjs check` and `tools/ci.sh --python-only` pass. For the follow-up tasks (M0-17 to M0-20) the verifier also checks that the earlier tests of the same criteria still pass. The milestone exit gate is in [the test plan](../test/test-plan-v4.md) (milestone exit gates) and SPEC-v5 section 17.

## 4. Open questions

> **Owner:** A · **Persona:** `planner`

- [x] Q: Should the next ECC run skip M0-01 to M0-05 (treat them as merged) or rebuild them? Options: (a) skip them and start at wave 4; (b) rebuild all. Recommendation: (a), because their unchanged criteria are `done` and the changed ones are in the follow-ups M0-17 to M0-20, which the run must still build. The generator emits every row, so a skip needs the run to be created with those units pre-merged; I could not verify how ECC does that. **Resolved (owner decision, 2026-10-23):** skip M0-01 to M0-03 in the next run (done and unchanged); rebuild the changed work through the follow-up tasks (M0-17 to M0-20).
- [x] Q: M0-04 and M0-05 are `done` too, but the decision above names only M0-01 to M0-03. Rebuilding them would rewrite `settings.py` and `platform/secrets.py`, which the follow-ups M0-19 and M0-20 also change. Options: (a) skip M0-01 to M0-05, which is what the generator does for every `done` row; (b) set M0-04 and M0-05 to `planned` and rebuild them before M0-19 and M0-20. Recommendation: (a), because their unchanged criteria (PLAT-9, PLAT-10, SEC-13) already pass on `main` and the changed ones are in M0-19 and M0-20. The owner decides. **Resolved (owner decision, 2026-10-23):** option (a): the run skips M0-01 to M0-05.
- [x] Q: LLD-sources-v2 §5.2 row 8 disagrees with PRD-search-v3 SRCH-FR-8 and LLD-search-v2 §5.4 on the state of a `rate_limited` source under `auto`. Options: (a) build `skipped_unhealthy` now (section 2.2, M0-09) and correct the sources LLD in its next version; (b) correct LLD-sources-v2 before the run. Recommendation: (a), because the PRD is approved and wins over an LLD. The owner decides. **Resolved (owner decision, 2026-10-23):** option (a): M0 builds `skipped_unhealthy`; the next version of the sources LLD carries the correction.
- [x] Q: The v1 plan said M0-06 and M0-08 have unmerged branches from the first run that cite the old test ids. This pass could not verify that (no branch record in `.orchestration`). If they exist, reuse them or discard them? Options: (a) discard and rebuild from this plan; (b) reuse as a starting point. Recommendation: (a) for M0-06, because it now depends on M0-20 and the v2 redaction design; (b) only for M0-08 if its tests are renamed to the SDD criteria and its schema matches LLD-cache-v2 §3.1. **Resolved (owner decision, 2026-10-23):** do not reuse old unmerged branches; rebuild M0-06 and M0-08 from this plan.
- [x] Q: PLAT-84 was expected to be an M0 criterion, but PRD-platform v4 and test plan v4 mark it M2. Options: (a) leave it in M2 (no M0 task); (b) pull it into M0 with a task on `pyproject.toml`, `uv.lock` and `tests/unit/test_version.py`, which M0-01 owns and says nobody else edits. Recommendation: (a); the owner decides, because (b) changes the PRD milestone and the M0 exit gate. **Resolved (owner decision, 2026-10-23):** option (a): PLAT-84 stays in M2; there is no M0 task for it.
