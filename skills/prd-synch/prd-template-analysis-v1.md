# PRD Template Analysis Against the SDD Framework (v1)

Oct 22, 2026 · Kenny

## Summary

The current PRD template has enough for problem framing, but too much for a PRD as a whole, and it skips two seed questions.

- **Seed question coverage:** 5 of the 12 are fully covered, 5 partially and 2 not at all. The missing two are invariants (question 5, what must never happen) and data classification (question 7).
- **Too much:** about half the template is design rather than requirements: all of Section 3 (Engineering Requirements), plus considered solutions, the recommended solution, the rollout plan, system monitoring and solution phases. In the framework these belong in the SPEC (HLD), ADRs, LLDs and the milestone plan, each approved at its own gate.
- **Missing mechanics:** there are no requirement IDs, no acceptance criteria in EARS, no priority on stories, no section for invariants, and no H, C or A owner tag (or persona) on any section.
- **Duplication:** five topics are asked for in two or three places.

The revised template (`PRD-template-revised-v1.md`) keeps what works, adds what is missing, and moves design content to the layers that own it.

## Seed question coverage

| # | Seed question | Template section | Coverage |
| --- | --- | --- | --- |
| 1 | What problem are we solving, for whom, and why now? | 1.1, 1.2, 1.3 | Full |
| 2 | What does success look like in numbers, and by when? | 1.5 | Partial: metrics, but no targets or dates |
| 3 | What are the top three things users must be able to do, in priority order? | 2.3, 2.7 | Partial: an MVP feature list, not ranked user stories |
| 4 | What is explicitly out of scope? | 2.11 | Full, but placed after the features it should bound |
| 5 | What must never happen? | None (2.6 legal and compliance is closest) | **Missing** |
| 6 | What are the latency, availability, scale and residency targets? | 2.8 mentions SLAs | Partial: no explicit targets |
| 7 | What data does it touch, and how is it classified? | None (2.8 "key data" means analytics data) | **Missing** |
| 8 | What systems must it integrate with or replace, and who owns them? | 2.5 dependencies, 2.1 stakeholders | Partial: no owners or SLAs per system |
| 9 | What is already fixed (stack, vendors, platforms, budget)? | 1.7 | Full |
| 10 | Which decisions are already made, and which are open? | 2.4, 3.5 | Partial: lists options but never asks what is already decided |
| 11 | What is the rollout risk tolerance, and who responds when it fails? | 2.13 | Partial: phases and kill switch, but no support owner |
| 12 | How will we know it is done? | 2.13 "must-pass" scenarios | Partial: no acceptance criteria or definition of done |

## Section by section

Owner tags follow the framework: **H** human-authored, **C** co-authored (agent drafts, human decides), **A** agent-generated.

### Header and Section 1: Alignment Overview

| Section | Owner | Belongs in | Action |
| --- | --- | --- | --- |
| Header (owner, contributors, date, related, status) | H | PRD header | Keep; add version, requirement ID prefix, parent and component PRD links |
| 1.1 Problem statement | H | PRD | Keep |
| 1.2 Market and strategic context | H | L0 vision; one "why now" paragraph in the PRD | Shorten and link out |
| 1.3 Customer and user personas | H | PRD | Keep |
| 1.4 Benefits of solving the problem | H | PRD | Keep the value content; move feasibility and viability to product risks, where they repeat |
| 1.5 Measurable outcomes | H | PRD | Keep; require a baseline, target and date for each metric |
| 1.6 Assumptions ("leaps of faith") | H | PRD | Keep; these are owner bets, distinct from the assumptions an agent surfaces |
| 1.7 Known constraints | H | PRD; standing constraints live in the constitution | Keep |
| 1.8 Decision makers | H | Header and approvals | Merge with 2.1 and 2.17 |
| Stop for approval before Section 2 | H | A problem gate before Gate 1 | Keep as Gate 0; it matches the brief that `sdd-intake` produces |

### Section 2: Product Requirements

| Section | Owner | Belongs in | Action |
| --- | --- | --- | --- |
| 2.1 Team and stakeholders | H | Header | Merge |
| 2.2 Customer discovery | A (`analyst`) | `docs/research/`, linked from the PRD | Move |
| 2.3 Feature definition (MVP) | C stories (`product-writer`), H priority | PRD | Keep; rewrite as user stories ranked P1 to P3 |
| 2.4 Considered solutions and problem-solution fit | C (`architect`) | ADRs | Move |
| 2.5 Recommended solution | C (`architect`) | SPEC (HLD); external dependencies go to integrations | Move; keep one line on what the user gets |
| 2.6 Risk management framework | H, except feasibility | PRD; feasibility goes to the HLD risk register | Keep value, usability and viability; move feasibility; turn legal and compliance "never" items into invariants |
| 2.7 E2E user experience and design | C | PRD, linking to design artifacts | Keep short and link the full design |
| 2.8 Known product requirements (FR and NFR) | H targets, A criteria (`product-writer`) | Parent and component PRDs | Keep and expand; this is the core of a PRD, and the template gives it one paragraph |
| 2.9 Detailed requirements document (optional) | n/a | Component PRDs | Replace with the parent plus component PRD structure |
| 2.10 Experimentation, measurement and monitoring | Split | Product metrics and experiments stay; system monitoring goes to LLD observability (`sre`) | Split |
| 2.11 Scope and out of scope | H | PRD, right after the problem | Keep and move up; drop its assumptions sentence, which repeats 1.6 |
| 2.12 Resourcing and prioritization | H | Portfolio planning; story priority sits on each story | Move out |
| 2.13 E2E testing and rollout plan | Split | Must-pass scenarios become acceptance criteria and the test plan (`test-architect`); phases and kill switch go to the HLD rollout section (`sre`); observability goes to the LLD; risk tolerance stays (H) | Split |
| 2.14 Solution phases (optional) | A (`planner`) | Milestone plan (L5), derived from story priority | Move |
| 2.15 Future opportunities (optional) | H | Vision (L0) or non-goals | Move |
| 2.16 Appendices (optional) | A | Links to research | Keep as links |
| 2.17 Approvals | H | Gate 1 | Keep |

### Section 3: Engineering Requirements

Section 3 is a system HLD plus ADR options inside the PRD. The template also asks for it "in parallel" with Section 2. In the framework, the HLD derives from an approved PRD and passes its own gate (Gate 2), so Section 3 becomes a separate SPEC (HLD) template and ADR template.

| Section | Owner | Belongs in | Action |
| --- | --- | --- | --- |
| 3.1 Questions | A | HLD open questions, resolved before Gate 2 | Move |
| 3.2 Solution architecture | C (`architect`) | SPEC (HLD) | Move |
| 3.3 Current state, pros and cons | A (`architect`) | HLD context; rationale inferred from existing code is tagged `[inferred]` | Move |
| 3.4 Principles | H | Constitution (standing principles) or the HLD | Move |
| 3.5 Options (preferred, architecture, cost, pros, cons) | C (`architect`) | ADRs; cost estimates go to the milestone plan | Move; keep the option format |
| 3.6 Testing requirements (platforms) | A (`test-architect`) | HLD testing strategy and the test plan | Move |
| 3.7 Outcome | H | ADR status and decision | Move |
| 3.8 Approvals | H | Gate 2 | Move |

### Appendix

| Section | Belongs in | Action |
| --- | --- | --- |
| Action items | Issue tracker or the milestone plan | Move |
| Prior art | `docs/research/` | Move |
| Decision log | ADRs plus the PRD's version history | Move |

## Duplication

| Topic | Asked in |
| --- | --- |
| Feasibility and viability | 1.4 and 2.6 |
| Assumptions | 1.6 and 2.11 |
| Decision makers | 1.8, 2.1 and 2.17 |
| Monitoring | 2.10 and 2.13 |
| Solution options | 2.4 and 3.5 |

## What works and is kept

- The stop for approval after Section 1, which becomes Gate 0 (problem approved).
- The "leaps of faith" test for assumptions.
- The four product risks: value, usability, feasibility and viability.
- The option format with cost, pros and cons, which moves to the ADR template.
- Kill-switch triggers, which move to the HLD rollout section; the owner's risk tolerance stays in the PRD.
- Readability rules: link out to detail, and remove instructional text before publishing.

## Conflict with the framework

The template calls the PRD a living document that is filled in over time. The framework uses numbered versions that are never edited after approval. The two fit together: Gate 0 approval produces v1, Gate 1 approval produces the next version, and every later change produces a new version rather than an edit.

## Revised structure

| Revised section | Owner | Seed question | Replaces |
| --- | --- | --- | --- |
| Header | H | n/a | Header, 1.8, 2.1 |
| **Section 1: Alignment (Gate 0)** | | | |
| 1.1 Problem and why now | H | 1 | 1.1, 1.2 |
| 1.2 Customers and users | H | 1 | 1.3 |
| 1.3 Scope and non-goals | H | 4 | 2.11 |
| 1.4 Measurable outcomes | H | 2 | 1.5 |
| 1.5 Value of solving the problem | H | 2 | 1.4 |
| 1.6 Leaps of faith | H | n/a | 1.6 |
| 1.7 Invariants: what must never happen | H | 5 | **New** |
| 1.8 Known constraints | H | 9 | 1.7 |
| 1.9 Decisions already made and still open | H | 10 | **New** |
| Gate 0 approvals | H | n/a | 1.8, stop line |
| **Section 2: Product requirements (Gate 1)** | | | |
| 2.1 Customer discovery | A | 1 | 2.2 |
| 2.2 User stories and priority | C, H priority | 3 | 2.3 |
| 2.3 User experience | C | 3 | 2.7 |
| 2.4 Functional requirements and acceptance criteria | A | 3, 12 | 2.8, 2.13 must-pass scenarios |
| 2.5 Non-functional requirements | H targets | 6 | 2.8 |
| 2.6 Data and classification | H | 7 | **New** |
| 2.7 Integrations and owners | H | 8 | 2.5 dependencies |
| 2.8 Product risks | H | n/a | 2.6 |
| 2.9 Rollout risk tolerance and support | H | 11 | 2.13 (in part) |
| 2.10 Measurement and experimentation | C | 2 | 2.10 (product metrics only) |
| 2.11 Definition of done | H | 12 | **New** |
| 2.12 Edge cases and error behavior | A | n/a | **New** |
| 2.13 Assumptions and open questions | A | n/a | **New** |
| 2.14 Glossary | A | n/a | **New** |
| Gate 1 approvals | H | n/a | 2.17 |
| **Moved out** | | | 2.4, 2.5, 2.12, 2.13 (in part), 2.14, 2.15, all of Section 3, Appendix |
