# Spec-Driven Development: Human vs Agent Ownership (v11)

Oct 20, 2026 · Kenny

## Bottom line

Humans write what cannot be derived (intent, boundaries, invariants, and irreversible decisions); agents write everything that can be derived from those answers, and humans approve at three gates: spec, HLD, and LLD. The human share shrinks as you move down the stack, from mostly human in the PRD to mostly agent in the LLD, but approval never drops to zero where a mistake is expensive to undo (public contracts, persisted schema, security paths).

The main failure mode in current tools is volume, not quality: agents generate more markdown than anyone will review, so every artifact below is kept short and each section has one owner.

The links between layers are plain text that a grep can follow: stable requirement IDs, cited by `@spec` comments in tests and code, checked in CI so a broken or missing link fails the build (see [Linking and tracking intent](#linking-and-tracking-intent)).

## Ownership tiers

Every section in the tables below carries one of three tags.

| Tag | Who writes | Who decides | Agent may |
| --- | --- | --- | --- |
| **H** Human-authored | Human (agent may interview to capture it) | Human | Ask questions, reformat; never invent content |
| **C** Co-authored | Agent drafts options or a first pass | Human picks, edits, signs off | Propose 2 to 3 options with tradeoffs |
| **A** Agent-generated | Agent, derived from H and C sections | Human reviews at the gate, or only on exception | Regenerate freely when upstream changes |

Every **A** and **C** section names the **agent persona** that writes it (tables below); **H** sections have none, though the `analyst` persona may interview the owner to capture them. Personas, their minimum requirements and where they live are in [Agent personas](#agent-personas).

One layer sits above all the documents: the **constitution** (Spec Kit's term; Kiro calls it steering). It holds org standards, the approved stack, security rules, and coding conventions. It is human-owned, written once per repo or org, and reused by every spec.

## Document layers

Each layer derives from the one above, and every requirement ID cites its parent, so a check can walk from a vision outcome down to a passing test. FR and NFR are sections inside the PRDs rather than layers of their own, and ADRs are decisions recorded at whatever layer makes them (most at the HLD). When the SPEC is the system-wide technical spec, it plays the HLD role, so the layer below it is per-component LLDs rather than a second HLD.

```mermaid
flowchart TB
    CON["Constitution: AGENTS.md (H)<br/>Rules, commands and definition of done<br/>that every layer and every agent obey"]

    L0["L0 Vision and strategy (H)<br/>Why, for whom, multi-year outcomes<br/>docs/vision/"]
    L1["L1 Parent PRD (H)<br/>Goals, non-goals, FR index, NFRs, metrics<br/>docs/prd/PRD-vN.md"]
    L2["L2 Component PRDs (H/C)<br/>Component FRs traced to parent FRs; EARS criteria<br/>docs/prd/components/"]
    L3["L3 SPEC, the system HLD (C)<br/>Architecture, data model, protocols, traceability<br/>docs/spec/SPEC-vN.md"]
    L4["L4 LLD, one per component (A)<br/>Contracts, schema, algorithms, test plan<br/>docs/lld/, docs/contracts/"]
    L5["L5 Milestone plan and tasks (A)<br/>Slices sized for one session, traced to IDs<br/>docs/build/Mn-plan-vN.md"]
    L6["L6 Code, tests, handoff (A)<br/>Verified against criteria; handoff records evidence<br/>src/, test/, docs/build/Mn-handoff-vN.md"]

    RES["Research (A)<br/>Prior art and spikes<br/>docs/research/"]
    ADR["ADRs (C)<br/>Decisions with options and tradeoffs<br/>Never versioned; a new ADR supersedes the old<br/>docs/adr/"]
    MAC["Machinery, not docs<br/>.claude/: skills, hooks<br/>tools/: spec-lint, trace-check<br/>docs/trace/: audit state (derived)<br/>CI runs both checks on every PR"]

    CON -. governs .-> L0
    L0 --> L1 --> L2 --> L3 --> L4 --> L5 --> L6

    RES -. informs .-> L0
    RES -.-> L1
    RES -.-> L2
    RES -.-> L3

    ADR -. decisions .- L2
    ADR -.- L3
    ADR -.- L4

    MAC -. runs .-> L5
    MAC -.-> L6

    classDef human fill:#e6eefb,stroke:#2f6fd6,stroke-width:2px
    classDef side fill:#ffffff,stroke:#a8a69e,stroke-dasharray:5 4
    class CON human
    class RES,ADR,MAC side
```

SVG version: [diagrams/sdd-doc-layers.svg](diagrams/sdd-doc-layers.svg)

Example trace, one ID per layer: FR-3 (parent PRD) → AUTH-2 (component PRD) → SPEC 4.2 → LLD-auth section 3 → M2 task 4 → the test and the code entry point that carry `// @spec AUTH-2`.

## PRD / Spec (the what and why)

The PRD is the most human document: about half its sections are H. It stays functional; no stack or design choices belong here.

| Section | Owner | Persona | Note |
| --- | --- | --- | --- |
| Problem statement, why now | H | none (`analyst` may interview) | The one thing an agent cannot know |
| Outcomes and success metrics (with targets) | H | none | Numbers and dates come from people |
| Users, personas, top jobs to be done | H | none (`analyst` may interview) | Agent can interview stakeholders to capture |
| Scope: in, out, non-goals | H | none | Prevents agent scope creep |
| Invariants: what must never happen | H | none | Security, compliance, data handling |
| NFR targets (latency, availability, scale, residency) | H | none (`product-writer` makes them testable) | Values are human; agent writes them as testable statements |
| Fixed constraints (deadline, vendors, platforms) | H | none | |
| User stories | C | `product-writer` | Human names the stories; agent writes them out |
| Acceptance criteria (EARS, or Given/When/Then) | A | `product-writer` | Derived per story, EARS by default (see below); human reviews at Gate 1 |
| Edge cases and error behavior | A | `product-writer` | Human spot-checks |
| Assumptions and open questions | A | `product-writer` | Agent surfaces; human resolves before Gate 1 |
| Glossary, requirement IDs, traceability | A | `product-writer` | |
| Research and prior art feeding the PRD | A | `analyst` | Linked sources only |

For larger efforts, use a parent PRD plus component PRDs that reference each other by requirement ID.

## EARS notation for acceptance criteria

Use EARS as the default notation for acceptance criteria so the spec linter can check each one by its keyword. Given/When/Then (Gherkin, from BDD) is an accepted alternative, and the better fit when criteria will run as executable scenarios in a BDD tool such as Cucumber. Pick one notation per spec rather than mixing them, so criteria stay easy to lint and trace.

| Pattern | Keyword | Template | Example |
| --- | --- | --- | --- |
| Ubiquitous | (none) | The *system* shall *response*. | The authorization service shall log every allow and deny decision with its policy ID. |
| Event-driven | When | When *trigger*, the *system* shall *response*. | When a user's role is revoked, the authorization service shall invalidate that user's cached grants within 60 seconds. |
| State-driven | While | While *state*, the *system* shall *response*. | While the policy store is unreachable, the authorization service shall deny all write requests. |
| Unwanted behavior | If / then | If *condition*, then the *system* shall *response*. | If a request carries an expired token, then the authorization service shall return 401 and record the attempt. |
| Optional feature | Where | Where *feature is included*, the *system* shall *response*. | Where step-up authentication is enabled, the authorization service shall require MFA for admin actions. |
| Complex | Combined | While *state*, when *trigger*, the *system* shall *response*. | While a session is active, when its token expires, the authorization service shall deny the request and return 401. |

Each criterion states one response, names the system as the subject, and is testable as written; the numbers in the examples are illustrative.

**Given/When/Then alternative.** The event-driven example in Gherkin form:

```gherkin
Given a user holds the Approver role
When that role is revoked
Then the authorization service invalidates the user's cached grants within 60 seconds
```

## HLD (the shape of the solution)

The HLD is where humans shift from authoring to deciding: the agent drafts options, and the human chooses among them.

| Section | Owner | Persona | Note |
| --- | --- | --- | --- |
| Architecture principles, approved stack | H | none | Lives in the constitution, not per spec |
| Key decisions as ADRs (build vs buy, sync vs async, data store, tenancy) | C | `architect` | Agent lays out options and tradeoffs; human decides |
| Trust boundaries and authorization model | C | `security-reviewer` | Human decides; agent drafts the threat model |
| System context and boundaries | C | `architect` | Agent drafts; human confirms what is in and out |
| Integrations and external dependencies | C | `architect` | Human confirms owners, SLAs, and access |
| Rollout and migration strategy | C | `sre` | Human sets risk tolerance; agent plans phases |
| Component breakdown and responsibilities | A | `architect` | |
| Data flow and sequence diagrams | A | `architect` | |
| Capacity and scaling estimates | A | `architect` | Derived from the NFR targets |
| Risks and mitigations | A | `architect` | Human ranks them at Gate 2 |
| Testing strategy | A | `test-architect` | Layers and tooling; per-criterion coverage lives in the test plan |

Watch for over-specification: if the HLD restates the PRD in different words, cut it.

## LLD (the build detail, one per component)

The LLD is almost entirely agent-generated; humans review only the parts that are costly to reverse.

| Section | Owner | Persona | Human review? |
| --- | --- | --- | --- |
| API contracts (OpenAPI, proto, events) | A | `component-designer` | **Yes** for any public or cross-team contract |
| Data model, schema, migrations | A | `component-designer` | **Yes** for anything persisted |
| AuthN/AuthZ enforcement points | A | `security-reviewer` | **Yes**, always |
| Module structure, interfaces, algorithms | A | `component-designer` | No, review the code instead |
| Error handling, retries, idempotency | A | `component-designer` | Spot-check |
| Config and feature flags | A | `component-designer` | No |
| Observability: metrics, logs, alerts | A | `sre` | Thresholds trace to NFRs; no separate review |
| Test plan, cases mapped to acceptance criteria | A | `test-architect` | Check coverage, not each case |
| Task list (dependency-ordered, traced to requirement IDs) | A | `planner` | Skim at Gate 3 |
| Code, tests and handoff | A | `implementer` | Code review; `verifier` checks traceability |

Each component LLD links back to its parent HLD section and the requirement IDs it satisfies. For an existing codebase, any rationale the agent infers from the code is tagged `[inferred]` until the owner confirms it.

## The seed questions

Yes: twelve answers are enough to derive the rest. Every H section above maps to one of these; the agent asks follow-ups only when an answer is missing or two answers conflict.

| # | Question | Feeds |
| --- | --- | --- |
| 1 | What problem are we solving, for whom, and why now? | PRD problem, personas |
| 2 | What does success look like in numbers, and by when? | Metrics, deadline |
| 3 | What are the top three things users must be able to do? | User stories, then ACs |
| 4 | What is explicitly out of scope? | Non-goals |
| 5 | What must never happen? | Invariants, threat model, security tests |
| 6 | What are the latency, availability, scale, and residency targets? | NFRs, capacity, alerts |
| 7 | What data does it touch, and how is it classified? | Data model, controls |
| 8 | What systems must it integrate with or replace, and who owns them? | Context, integrations |
| 9 | What is already fixed (stack, vendors, platforms, budget)? | Constitution check, ADR limits |
| 10 | Which decisions are already made, and which are open? | ADR options |
| 11 | What is the rollout risk tolerance (flags, canary, rollback)? | Rollout plan |
| 12 | How will we know it is done (demo, test, metric)? | Test plan, Definition of Done |

Questions 9 and 10 are usually answered once in the constitution and only revisited per spec when something changes.

## Agent personas

A persona is a named, scoped role an agent plays when it writes or reviews part of a document. Eleven cover every A and C section above. The minimum requirements are small enough to summarize here; the full standard and roster are a separate file in the repository (`docs/standards/agent-personas-v1.md`).

| Persona | Writes (A) | Drafts for a decision (C) | Gate |
| --- | --- | --- | --- |
| `analyst` | Research, prior art, the intake record of the owner's answers | None; may interview for H sections | Before Gate 1 |
| `product-writer` | EARS criteria, edge cases, assumptions, glossary, IDs | User stories | Gate 1 |
| `architect` | Component breakdown, data flow, capacity, risks | ADR options, system context, integrations | Gate 2 |
| `security-reviewer` | Security sections of LLDs (always human-reviewed) | Trust boundaries, threat model | Gates 2, 3 |
| `component-designer` | LLD structure, algorithms, errors, config, contracts, schema | None | Gate 3 |
| `test-architect` | Test plan, with coverage regenerated from `@spec` annotations; gaps | None | Gate 3 |
| `sre` | Observability, runbooks, operations sections | Rollout and migration | Gates 2, 3 |
| `planner` | Milestone plans, slices, tasks | None | Gate 3 |
| `implementer` | Code and tests carrying `@spec` annotations, handoff | None | Code review |
| `verifier` | Traceability, drift and annotation reach findings; audit index; optional divergence probe and differential audits | None | Every gate (independent) |
| `doc-steward` | Doc map, glossary, version and link hygiene | None | None (mechanical) |

**Minimum requirements for every persona definition.**

1. Identity: `name` (kebab case, matches the file) and a one-sentence `description` of when to use it.
2. Purpose: one paragraph.
3. Owned sections, each tagged A or C; never an H section.
4. Inputs, in reading order: the constitution first, then the layer above its output.
5. Outputs: exact files and format; always the next numbered version, never an edit to a past one.
6. Tools: least privilege; reviewers are read-only plus check commands.
7. Boundaries: never invent H content, never approve or verify its own work, never edit another persona's section, cite IDs, mark assumptions.
8. Gate and handoff: which human gate reviews it and who receives its output.
9. Definition of done: the checks it runs before handing off.
10. Escalation: when it stops and asks (missing or conflicting H answers, anything irreversible).

**Where they live.** Each persona's runnable definition is a markdown file in `.claude/agents/<name>.md`, versioned with the code; Claude Code discovers subagents there, and `AGENTS.md` points other agents (Codex) to the same files. The requirements standard sits with the other human-reviewed standards in `docs/standards/`. Neither belongs in `tools/`, which is for executable checks, and personas are not a layer of the spec stack. Each template section's owner line names its persona, so assignments travel with every new document.

## Tooling and skills to build

Build eight small skills that run in sequence, with a hard stop at each human gate; extend Spec Kit's commands and templates rather than starting from scratch, since it already runs in Claude Code and is fully customizable. Humans enter the chain at four points (shaded); agents do the rest.

```mermaid
flowchart TB
    HIN(["Human input<br/>Answers the 12 seed questions"])
    S1["sdd-intake<br/>Interviews the human with the 12 seed questions; writes brief.md"]
    S2["sdd-spec<br/>Brief + constitution to spec.md: stories, EARS criteria, NFRs"]
    S3["sdd-clarify<br/>Finds gaps and conflicts; optional blind divergence probe; asks the human only what is missing"]
    G1{{"Gate 1<br/>Human approves the spec"}}
    S4["sdd-hld<br/>Spec to hld.md, diagrams, and ADR options with tradeoffs"]
    G2{{"Gate 2<br/>Human picks ADRs, approves HLD"}}
    S5["sdd-lld<br/>One LLD per component: contracts, schema, test plan, linked IDs"]
    G3{{"Gate 3<br/>Human reviews contracts, schema, authZ"}}
    S6["sdd-tasks<br/>Small, dependency-ordered tasks, each traced to requirement IDs"]
    S7["sdd-implement<br/>Executes one task at a time, tests first; @spec on each test and entry point"]
    S8["sdd-verify<br/>Structural trace checks, then optional blind differential; flags drift from the spec"]

    HIN --> S1 --> S2 --> S3 --> G1 --> S4 --> G2 --> S5 --> G3 --> S6 --> S7 --> S8
    S8 -. "drift found: update the spec, then design and tasks regenerate" .-> S2

    classDef human fill:#e6eefb,stroke:#2f6fd6,stroke-width:2px
    class HIN,G1,G2,G3 human
```

SVG version: [diagrams/sdd-skill-chain.svg](diagrams/sdd-skill-chain.svg)

The loop back from sdd-verify to sdd-spec is what makes the spec a living artifact (spec-anchored) instead of a throwaway prompt.

| Supporting piece | Purpose |
| --- | --- |
| constitution.md | Human-owned standards every skill reads first |
| Templates per artifact | Fixed sections tagged H, C, or A, so the agent cannot skip or invent sections |
| Spec linter | Fails on missing requirement IDs, criteria not in an EARS pattern or Given/When/Then form, untestable criteria, or unresolved open questions |
| Gate hook | Blocks the next skill until the prior artifact is marked approved |
| Size router | Sends bugs and small changes down a short path (spec plus tasks only); a change that crosses components stops for a human |
| Traceability check in CI (`trace-check`) | Fails on reverse orphans, uncovered criteria and hollow status; warns on stale components; reports annotation reach; every task cites an ID |
| Audit index | `docs/trace/index.yaml`: per-component status, commit at last audit, drift, next action |

## Linking and tracking intent

A trace is only as good as the links that carry it. Links are plain text that a grep can follow, tracking state lives only in derived files, and the structural checks fail the build. This section adapts Linked-Intent Development (LID); [Appendix A](#appendix-a-lid-adopted-or-not-using) lists what is adopted.

**How a link is made.**

- Every requirement keeps one stable ID for life: never renumbered, and never reused after deletion.
- Tests and code cite the IDs they satisfy in a comment. The annotation goes on the test that exercises the behavior and on the entry point of the behavior in code (the topmost function or handler that owns it), not on every helper. A behavior that spans subsystems gets one annotation per subsystem entry point.
- `@spec` cites acceptance criterion IDs, because in this framework requirements come from the product layers and the design implements them. References to SPEC or LLD sections go in the handoff, not in code.
- Every hop is then one grep, in either direction: ID to criterion, ID to tests, ID to code.

```ts
// @spec AUTH-2
it('invalidates cached grants within 60 seconds of role revocation', async () => { /* ... */ });
```

**Where tracking state lives.**

| State | Home | Written by |
| --- | --- | --- |
| Per criterion: covered, gap, deferred | Test plan, regenerated from the annotations | `test-architect`, through `trace-check` |
| Per component: status, commit at last audit, drift, next action | `docs/trace/index.yaml` | `verifier` |
| Differential audit records | `docs/trace/audits/<component>/<ID>.md` | `verifier` |

Status never goes inside a versioned document, because past versions are frozen; the derived files can be regenerated at any time. Recording the commit at each audit lets the verifier re-check only the components whose files changed since then.

**Structural checks.** `trace-check` runs in CI; the first three fail the build.

1. Reverse orphan: an annotation cites an ID that no document defines.
2. Uncovered: a criterion that is not deferred has no test citing it.
3. Hollow status: a criterion is marked covered, but nothing cites it.
4. Stale (warning): a component's files changed since its last audit, or it has not been audited within the agreed window.

**Annotation reach.** The checks only see what is annotated, and the agent that writes the code also places the annotations, so under-annotating is the cheapest way to pass. Track reach, the share of behavior-bearing changed lines covered by some `@spec`, on every pull request, and treat a falling number as a code review finding.

**Semantic verification.** Structural checks prove that links exist, not that the linked things agree. Two optional verifier modes, each behind a feature flag, use readers that have no context:

- Divergence probe (in `sdd-clarify`, before Gate 1): blind readers give two or three plausible readings of each new criterion; every genuine fork goes back to the owner and lands as a narrower criterion.
- Bidirectional differential (in `sdd-verify`): with IDs and requirement-echoing names stripped from the code, some blind sessions implement the criterion from its text alone while others reconstruct the criterion from the code, and the two are compared by behavior. Disagreement names the drift: hollow tests, unstated behavior, or criteria the code does not meet.

LID's own trial caught 23 of 24 planted gaps on annotated code and missed the one gap in unannotated code. Its published critique notes a single codebase, a small sample and no human baseline, so treat the differential as an aid at Gate 3 and code review, not a replacement for either.

**Cascade.** A change inside one component cascades freely to its LLD, tests and code in the same change. A change that crosses components stops for a human and goes into the next HLD version, with an ADR when the system's shape changes. Bug fixes walk the same path: find the layer where behavior left intent, and change that layer first.

**Constitution rules this adds.**

- Memory vs intent: project knowledge that an agent would need in its next session goes into the docs, not into an agent's private memory.
- Placement: each decision and term lives at the lowest layer or component that covers everything it affects.

## Repository layout

The rule of thumb: `docs/` holds what humans review (the what and why), `.claude/` and `tools/` hold what agents run (the how), and `AGENTS.md` at the root is the bridge every agent loads first.

```text
repo/
├── AGENTS.md                               # Constitution: rules, commands, definition of done (H)
├── CLAUDE.md                               # One line: @AGENTS.md
├── docs/                                   # What humans review: the what and why
│   ├── README.md                           # Doc map: layers, latest version of each, ID scheme
│   ├── glossary.md                         # Domain terms and definitions
│   ├── vision/                             # L0: vision and strategy (H)
│   │   └── vision-v1.md
│   ├── research/                           # Inputs to L0 to L3: prior art, spikes, benchmarks (A)
│   │   └── auth-token-storage-v1.md
│   ├── prd/                                # L1 and L2: product requirements
│   │   ├── PRD-v1.md                       # L1 parent: goals, FR index, NFRs, metrics (H)
│   │   └── components/                     # L2: component PRDs with EARS criteria (H/C)
│   │       ├── PRD-auth-v1.md
│   │       └── PRD-billing-v1.md
│   ├── adr/                                # Decisions; superseded, never versioned (C)
│   │   ├── 0001-use-postgresql.md
│   │   └── 0002-jwt-token-revocation.md
│   ├── spec/                               # L3: system HLD and PRD-to-spec traceability (C)
│   │   └── SPEC-v1.md
│   ├── lld/                                # L4: one LLD per component (A)
│   │   ├── LLD-auth-v1.md
│   │   └── LLD-billing-v1.md
│   ├── contracts/                          # Interface specs, data models, tool definitions (A)
│   │   ├── openapi.yaml                    # REST API specification
│   │   ├── session-event.schema.json       # JSON Schema for payload and storage validation
│   │   └── agent-tools.json                # Agent tool and function-calling schemas
│   ├── test/                               # Criteria-to-test matrix (A)
│   │   └── test-plan-v1.md                 # Coverage regenerated from @spec annotations
│   ├── trace/                              # Audit state; derived, never versioned
│   │   ├── index.yaml                      # Per component: status, last audited commit, drift, next
│   │   └── audits/                         # Differential audit records, one per criterion
│   │       └── auth/
│   │           └── AUTH-2.md
│   ├── build/                              # L5 milestone plans and L6 evidence (A)
│   │   ├── M1-kickoff-v1.md
│   │   ├── M1-plan-v1.md
│   │   └── M1-handoff-v1.md
│   ├── runbooks/                           # Operational and incident procedures (A)
│   │   └── db-failover-v1.md
│   ├── templates/                          # One per artifact; sections tagged H, C or A with persona
│   │   ├── PRD-template.md
│   │   ├── SPEC-template.md
│   │   └── LLD-template.md
│   ├── standards/                          # Human-approved standards
│   │   ├── spec-driven-development-v1.md
│   │   └── agent-personas-v1.md            # Persona minimum requirements and roster
│   └── assets/
│       └── diagrams/                       # Diagram sources and rendered SVGs
│           ├── sdd-doc-layers.svg
│           ├── sdd-skill-chain.svg
│           ├── auth-sequence.mmd           # Mermaid source
│           └── auth-sequence.svg           # Rendered from the source
├── .claude/                                # What agents run: Claude Code machinery, versioned with the code
│   ├── skills/                             # The eight SDD skills, run in this order
│   │   ├── sdd-intake/
│   │   │   └── SKILL.md
│   │   ├── sdd-spec/
│   │   │   └── SKILL.md
│   │   ├── sdd-clarify/
│   │   │   └── SKILL.md
│   │   ├── sdd-hld/
│   │   │   └── SKILL.md
│   │   ├── sdd-lld/
│   │   │   └── SKILL.md
│   │   ├── sdd-tasks/
│   │   │   └── SKILL.md
│   │   ├── sdd-implement/
│   │   │   └── SKILL.md
│   │   └── sdd-verify/
│   │       └── SKILL.md
│   ├── agents/                             # One file per persona
│   │   ├── analyst.md
│   │   ├── product-writer.md
│   │   ├── architect.md
│   │   ├── security-reviewer.md
│   │   ├── component-designer.md
│   │   ├── test-architect.md
│   │   ├── sre.md
│   │   ├── planner.md
│   │   ├── implementer.md
│   │   ├── verifier.md
│   │   └── doc-steward.md
│   ├── commands/                           # Slash commands that wrap the skills
│   │   ├── sdd-new.md                      # Starts a spec: runs sdd-intake, then sdd-spec
│   │   └── sdd-check.md                    # Runs spec-lint and trace-check locally
│   └── settings.json                       # Hooks, including the gate hook
├── .claude-plugin/                         # Packages the skills for other repos and machines
│   └── plugin.json
├── tools/                                  # Executable checks, run by CI
│   ├── spec-lint/                          # IDs, EARS or Given/When/Then, open questions
│   │   ├── README.md
│   │   └── spec-lint.mjs
│   └── trace-check/                        # Orphans, coverage, hollow status, staleness, reach
│       ├── README.md
│       └── trace-check.mjs
├── src/                                    # Code; behavior entry points carry @spec annotations
│   └── auth/
│       └── revoke-role.ts                  # Revocation handler carries @spec AUTH-2
├── test/                                   # Tests; each cites the criteria it verifies with @spec
│   └── auth/
│       └── revoke-role.test.ts             # The test that exercises it carries @spec AUTH-2
└── .github/
    └── workflows/
        └── ci.yml                          # Typecheck, tests, spec-lint, trace-check
```

**Where the machinery goes.**

| Thing | Home | Why |
| --- | --- | --- |
| Rules | `AGENTS.md`, with long topic rules split into files it links to | Every agent loads it; Codex reads `AGENTS.md`, Claude Code reaches it through `CLAUDE.md` |
| Skills | `.claude/skills/`, packaged through `.claude-plugin/` for reuse | Where Claude Code discovers them; the plugin carries them to other repos |
| Loops | Inside the skill or command that runs them; the stop condition goes in the definition of done | A loop is behavior, not a document |
| Verification | Scripts in `tools/`, run by CI; audit state in `docs/trace/`; evidence in `docs/build/*-handoff` | The check is code; the record of what passed is a document |
| Templates | `docs/templates/` | Humans review the section list, the H, C, A tags and the persona per section |
| Personas | Definitions in `.claude/agents/`; the requirements standard in `docs/standards/` | Runnable by Claude Code, linked from `AGENTS.md` for other agents, reviewed as a standard |

**Conventions that keep the tree traceable.**

1. Every versioned document is `<name>-vN.md`; past versions are never edited, the next number is created instead.
2. ADRs are the exception: numbered once, with a Status line, and superseded by a new ADR rather than versioned.
3. `docs/README.md` lists the latest version of each document, so agents never have to search for it.
4. Every acceptance criterion has a stable ID, never renumbered or reused; tests and code cite it with `@spec`, which is what `trace-check` matches.
5. Status (covered, gap, deferred, drift) lives only in derived files (the test plan and `docs/trace/`), never in a versioned document.

## Appendix A: LID, adopted or not using

| LID element | Status | Where in this framework |
| --- | --- | --- |
| `@spec` annotations and stable IDs | Adopted | Linking and tracking intent |
| Structural checks: reverse orphans, coverage, staleness | Adopted | `trace-check` |
| Audit index with the last audited commit | Adopted | `docs/trace/index.yaml` |
| Divergence probe and bidirectional differential | Adopted | `sdd-clarify`, `sdd-verify` (behind a flag) |
| Cascade rules; bug fixes walk the arrow | Adopted | Cascade |
| Memory vs intent, placement, `[inferred]` rationale | Adopted | Constitution rules; LLD |
| Path-concatenated IDs and rename tooling | Not using | |
| Spec files and status markers beside each design doc | Not using | |
| Current-intent docs, recursive design tree, arrow docs | Not using | |
| Mandatory stop after every phase; advisory-only checks | Not using | |
| Modes, capability flags, coach and mapping commands | Not using | |

## Sources

- [Understanding Spec-Driven Development: Kiro, spec-kit, and Tessl](https://www.martinfowler.com/articles/exploring-gen-ai/sdd-3-tools.html), Birgitta Böckeler (levels of SDD, review overload, sizing)
- [Spec-driven development with AI: Spec Kit launch](https://github.blog/2025-09-02-spec-driven-development-with-ai-get-started-with-a-new-open-source-toolkit/), GitHub (constitution, steer and verify)
- [Kiro Specs: Requirements to Code](https://www.verdent.ai/guides/agents/kiro-spec-driven-development) (requirements, design, tasks; EARS; over-specification signal)
- [spec-driven-development skill](https://hackernoon.com/skills/addyosmani-spec-driven-development), Addy Osmani (human gate per phase, task sizing)
- [What Is the BMAD Method?](https://www.augmentcode.com/guides/bmad-method-ai-development) (Analyst, PM, Architect roles; brief to PRD to architecture)
- [spec-driven-development skill](https://tessl.io/registry/kevin-ryan-io/spec-driven-development/files/SKILL.md), Tessl registry (brief as the spec for the spec)
- [Linked-Intent Development (LID)](https://github.com/jszmajda/lid), jszmajda (`@spec` annotations, arrow index, coherence check, cascade discipline, divergence probe)
- [B10 differential catch rate: results](https://github.com/jszmajda/lid/blob/main/docs/research/experiments/b10-differential-catch-rate/RESULTS.md) and [critique](https://github.com/jszmajda/lid/blob/main/docs/research/experiments/b10-differential-catch-rate/CRITIQUE.md), LID (evidence for and limits of the bidirectional differential)
