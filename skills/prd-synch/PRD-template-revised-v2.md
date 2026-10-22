# [Product Title]: [One-Line Tagline]

| Field | Value |
| --- | --- |
| Document owner | [Name] |
| Contributors | [Names and roles] |
| Decision makers | [Who approves Gate 0 and Gate 1] |
| Version | v[N] *(an approved version is never edited; changes go into the next version)* |
| Status | Draft · Ready for review · Approved at Gate 0 · Approved at Gate 1 |
| Requirement ID prefix | [PREFIX] *(for example `IAM`; every ID in this document starts with it)* |
| Parent PRD | [Link, or "none" if this is the parent] |
| Component PRDs | [Links, or "none"] |
| Related | Vision: [link] · Research: [link] · SPEC: [link once written] · ADRs: [links] |

## How to use this template

*Delete this section and all italic guidance before publishing.*

*Every section has an owner tag and, where an agent writes or drafts it, the persona that does so:*

| Tag | Who writes | Who decides |
| --- | --- | --- |
| **H** Human-authored | The owner; an agent may interview to capture it, but never invents it | The owner |
| **C** Co-authored | The named persona drafts options or a first pass | The owner edits and signs off |
| **A** Agent-generated | The named persona, derived from the H and C sections | The owner reviews at the gate |

*The PRD states the **what** and **why**, never the **how**. Solution options, architecture, rollout plans, system monitoring, test plans and task phasing belong in the SPEC (HLD), ADRs, LLDs and the milestone plan. If a section starts describing a design, link to the design instead.*

*Section 1 is approved at **Gate 0** (problem approved) before Section 2 begins. Section 2 is approved at **Gate 1** (requirements approved). Each approval produces a new version.*

*Every requirement gets an ID that never changes and is never reused: outcomes `[PREFIX]-OUT-n`, invariants `[PREFIX]-INV-n`, user stories `[PREFIX]-US-n`, functional requirements `[PREFIX]-FR-n`, acceptance criteria `[PREFIX]-AC-n`, NFRs `[PREFIX]-NFR-n`. Tests and code cite these IDs with `@spec`.*

*For a large effort, write one parent PRD (Section 1 plus the FR index and NFRs) and one component PRD per component (its stories, FRs and acceptance criteria). They reference each other by ID.*

*Keep it short. Link to research, designs and decks rather than pasting them in.*

---

## Section 1: Alignment

*Prove that the problem exists, that it matters now, and that solving it is worth more than it costs. Stop for Gate 0 approval at the end of this section.*

### 1.1 Problem and why now

> **Owner:** H · **Persona:** none (`analyst` may interview) · **Seed question:** 1

*Describe the problem or opportunity in terms of user, customer or business need, with the data that proves it is real. In one paragraph, say why it must be solved now rather than later and which strategic goal it advances; link the strategy or vision document instead of restating it. List existing internal systems that address similar problems.*

### 1.2 Customers and users

> **Owner:** H · **Persona:** none (`analyst` may interview) · **Seed question:** 1

*Who is this for, what do they need, and how many of them are there? For internal platforms, include the buyer and other key stakeholders as well as the direct user.*

| User or stakeholder | Need | Relative size |
| --- | --- | --- |
| | | |

### 1.3 Scope and non-goals

> **Owner:** H · **Persona:** none · **Seed question:** 4

*What is in scope, and what is explicitly not (with a reason for each exclusion)? Clarity here prevents scope creep, including scope creep by agents.*

**In scope**

- 

**Out of scope (non-goals)**

| Non-goal | Why it is excluded |
| --- | --- |
| | |

### 1.4 Measurable outcomes

> **Owner:** H · **Persona:** none · **Seed question:** 2

*Two or three "North Star" metrics that prove the problem is solved. Every metric needs a baseline, a target and a date; numbers and dates come from people, not agents.*

| ID | Metric | Baseline | Target | By when |
| --- | --- | --- | --- | --- |
| [PREFIX]-OUT-1 | | | | |

### 1.5 Value of solving the problem

> **Owner:** H · **Persona:** none · **Seed question:** 2

*Describe and quantify the value to the business and to users, the risks this work reduces, and how it aligns with stakeholder priorities. Feasibility and viability belong in 2.8 (Product risks).*

### 1.6 Leaps of faith

> **Owner:** H · **Persona:** none

*Two or three foundational bets that must hold for this to succeed (user behavior, market readiness, technical viability). Test each one: if it turned out to be false, would we still build this? If not, it belongs here, along with how it will be validated. Assumptions that agents surface while writing requirements go in 2.13 instead.*

| Leap of faith | How we will validate it | By when |
| --- | --- | --- |
| | | |

### 1.7 Invariants: what must never happen

> **Owner:** H · **Persona:** none · **Seed question:** 5

*The things this product must never do, regardless of feature or load: security, privacy, compliance, regulatory and data-handling rules. Each invariant becomes a P1 acceptance criterion, a security test, and an S0 or S1 incident if it is ever breached.*

| ID | The system must never | Source (regulation, policy, contract) |
| --- | --- | --- |
| [PREFIX]-INV-1 | | |

### 1.8 Known constraints

> **Owner:** H · **Persona:** none · **Seed question:** 9

*Constraints specific to this effort: deadlines, budget, vendors, platforms, required approvals (legal, compliance, cyber), resourcing, and dependencies leadership must know about. Standing constraints (the approved stack, organization-wide rules) live in the constitution; link to them rather than repeating them.*

### 1.9 Decisions already made and still open

> **Owner:** H · **Persona:** none · **Seed question:** 10

*List decisions that are already settled (and why), so design does not reopen them, and decisions that are still open. Open decisions become ADR options at the HLD stage; do not argue options here.*

| Decision | Status (made or open) | Rationale or link |
| --- | --- | --- |
| | | |

### Gate 0: Problem approved

> **Owner:** H

*Stop here. Section 2 starts only after the decision makers approve Section 1.*

| Approver | Date | Notes |
| --- | --- | --- |
| | | |

---

## Section 2: Product requirements

*Turn the approved problem into requirements that can be designed, built and tested. Work iteratively, but every section must be complete, and every open question resolved, before Gate 1.*

### 2.1 Customer discovery

> **Owner:** A · **Persona:** `analyst`

*Summarize what research and discovery found: the method, what was measured or observed, and what changed as a result. Link the full findings in `docs/research/`.*

### 2.2 User stories and priority

> **Owner:** C for stories (`product-writer`), H for priority · **Seed question:** 3

*The owner names the stories and sets each one's priority; the `product-writer` writes them out. P1 stories are the MVP: each must be independently testable and deliver value on its own.*

*Priority: **P1** must ship for the release to have value; **P2** should ship, but the release has value without it; **P3** could ship (backlog, re-ranked each milestone).*

| ID | As a... I want... so that... | Priority | Why this priority |
| --- | --- | --- | --- |
| [PREFIX]-US-1 | | P1 | |

### 2.3 User experience

> **Owner:** C · **Persona:** `product-writer` drafts the narrative; designers own the design artifacts · **Seed question:** 3

*The most important user journeys and flows, as a short narrative of what the user sees and does. Link the full design (sketches, wireframes, prototypes) rather than embedding it. Reference the story IDs each flow covers.*

### 2.4 Functional requirements and acceptance criteria

> **Owner:** A · **Persona:** `product-writer` · **Seed questions:** 3, 12

*Each functional requirement traces to a story; each acceptance criterion traces to a requirement and is written in EARS (or Given/When/Then, one notation per document). Criteria inherit their story's priority. Include regulatory, audit logging and error escalation requirements.*

| ID | Requirement | Story | Priority |
| --- | --- | --- | --- |
| [PREFIX]-FR-1 | | [PREFIX]-US-1 | P1 |

*Acceptance criteria, one response each, with the system named as the subject:*

| ID | Criterion | Requirement |
| --- | --- | --- |
| [PREFIX]-AC-1 | When *trigger*, the *system* shall *response*. | [PREFIX]-FR-1 |

*EARS patterns: ubiquitous (The system shall...), event-driven (When...), state-driven (While...), unwanted behavior (If... then...), optional feature (Where...).*

### 2.5 Non-functional requirements

> **Owner:** H for targets; `product-writer` makes them testable · **Seed question:** 6

*Target values come from people. Cover at least latency, availability, scale, data residency, accessibility and auditability. NFRs are always P1.*

| ID | Quality | Target | How it is measured |
| --- | --- | --- | --- |
| [PREFIX]-NFR-1 | Latency | | |
| [PREFIX]-NFR-2 | Availability | | |
| [PREFIX]-NFR-3 | Scale | | |
| [PREFIX]-NFR-4 | Data residency | | |

### 2.6 Data and classification

> **Owner:** H · **Persona:** none · **Seed question:** 7

*Every kind of data the product reads, writes or stores, and how it is classified. Controls are derived from this table in the LLD, so a missing row means a missing control.*

| Data | Classification | Source or owner | Retention | Notes |
| --- | --- | --- | --- | --- |
| | | | | |

### 2.7 Integrations and owners

> **Owner:** H confirms owners and SLAs · **Persona:** `architect` may draft the list · **Seed question:** 8

*Systems this product depends on, feeds, or replaces, and who owns each one. The technical integration design belongs in the HLD.*

| System | Owner | Relationship (depends on, feeds, replaces) | SLA | Status of agreement |
| --- | --- | --- | --- | --- |
| | | | | |

### 2.8 Product risks

> **Owner:** H · **Persona:** none

*The product risks the owner must judge. Feasibility (can we build and run it?) is assessed in the HLD risk register.*

| Risk | Question | Assessment | Mitigation |
| --- | --- | --- | --- |
| Value | Will customers choose to use this over alternatives? | | |
| Usability | Can customers use it, including with accessibility needs? | | |
| Viability | Does it work for the business: economics, legal, compliance, operations, reputation? | | |

*List the risk and compliance reviews required before build or launch, and summarize any findings from legal and risk partners that could add requirements or stop the work. Any "must never" items belong in 1.7 (Invariants).*

### 2.9 Rollout risk tolerance and support

> **Owner:** H · **Persona:** none · **Seed question:** 11

*The owner's appetite for risk at launch and who responds when things fail. The `sre` derives the rollout plan, kill-switch mechanics and runbooks from this in the HLD and LLD.*

| Question | Answer |
| --- | --- |
| Rollout appetite (internal only, staged percentages, full launch) | |
| Business conditions that must halt or reverse the rollout | |
| Who responds when it fails (support owner and escalation path) | |
| Response targets by severity (S0 to S4) | |

### 2.10 Measurement and experimentation

> **Owner:** C · **Persona:** `product-writer` drafts; the owner decides

*How each outcome in 1.4 will be measured (the events or data to capture), and any experiments: hypothesis, audience, treatments and success metric. System health monitoring (dashboards, alerts) belongs in the LLD.*

| Outcome | Measured by | Experiment (if any) |
| --- | --- | --- |
| [PREFIX]-OUT-1 | | |

### 2.11 Definition of done

> **Owner:** H · **Persona:** none · **Seed question:** 12

*What must be true to call this release done: which criteria pass, what is demonstrated, and which outcome metrics must be measurable (not yet met) at launch.*

### 2.12 Edge cases and error behavior

> **Owner:** A · **Persona:** `product-writer` · **Owner spot-checks**

*Boundary conditions, failure modes and what the user sees in each. Each one that changes behavior becomes an acceptance criterion in 2.4.*

### 2.13 Assumptions and open questions

> **Owner:** A · **Persona:** `product-writer` surfaces; the owner resolves

*Assumptions and questions found while writing the requirements. Every open question must be resolved before Gate 1. The owner's bets live in 1.6 (Leaps of faith).*

| Item | Type (assumption or question) | Resolution |
| --- | --- | --- |
| | | |

### 2.14 Glossary

> **Owner:** A · **Persona:** `product-writer`

*Domain terms used in this PRD, defined once. Terms used across PRDs go in the project glossary.*

| Term | Definition |
| --- | --- |
| | |

### Gate 1: Requirements approved

> **Owner:** H

| Approver | Date | Notes |
| --- | --- | --- |
| | | |

---

## Appendix: Where the rest goes

*Content that the previous template kept in the PRD now lives in the layer that owns it. Link to it from the header once it exists.*

| Content | Lives in | Written by |
| --- | --- | --- |
| Considered solutions and solution options with cost, pros and cons | ADRs | `architect` (C) |
| Recommended solution and solution architecture | SPEC (HLD) | `architect` (C) |
| Current state, principles and technical questions | SPEC (HLD); standing principles in the constitution | `architect` (A, C) |
| Feasibility risk | HLD risk register | `architect` (A) |
| Rollout phases and kill-switch mechanics | HLD rollout section | `sre` (C) |
| System monitoring and alerts | LLD observability | `sre` (A) |
| E2E test scenarios and testing requirements | Test plan | `test-architect` (A) |
| Solution phases | Milestone plan | `planner` (A) |
| Resourcing and portfolio priority | Portfolio planning | Owner (H) |
| Future opportunities | Vision | Owner (H) |
| Customer research and prior art | `docs/research/` | `analyst` (A) |
| Action items | Issue tracker | Owner (H) |
| Decision log | ADRs and this document's version history | Owner (H) |
