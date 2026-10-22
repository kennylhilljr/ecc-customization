# SDD Framework Repository Alignment Analysis

**Reviewed:** October 22, 2026  
**White paper:** [Access Management SDD Framework White Paper v2](</Users/bkh223/Documents/Codex/2026-10-22/an/outputs/Access Management SDD Framework White Paper v2.docx>)  
**Repository:** `/Users/bkh223/Documents/GitHub/sdd_framework` and `github.com/kennylhilljr/sdd_framework`  
**Reviewed revision:** `6d7e15ee9a946381cd213fd9cf26a08e50fb8311`

## Executive assessment

The local checkout and GitHub `main` resolve to the same commit. The local branch is clean, so this review applies to both copies without a local-versus-remote qualification.

The repository is a credible working prototype, but it is not yet aligned with the white paper's operating model. Its strongest elements are versioned documents, named ownership, approval gates, stable requirement identifiers, structural trace checks, scaffolding, and a complete example that reaches code and tests. Its main weakness is that the documentation gives the same labels to different concepts.

The largest conflict is the use of **L0 through L6 for document stages**. The white paper reserves **L0 through L3 for organizational scope**:

| Scope level | Meaning |
| --- | --- |
| L0 | Cyber and Cyber IAM strategy, declarations, and imperatives |
| L1 | Domain, with Access Management as the example domain implementing the framework |
| L2 | Solution or capability, such as Entitlement Management or Access Certifications |
| L3 | Business Application |

The repository should stop using L numbers for Vision, PRDs, design, plans, and handoffs. Those items belong to an unnumbered **delivery artifact chain**. Gate numbers should remain a third and separate concept.

The second major gap is positioning. The README currently presents a generic framework for AI coding agents. The white paper presents SDD first as a controlled bridge between Product and Engineering, with agents supporting that bridge. It also presents the repository as an Access Management reference implementation that is being built and iterated, not as a finished enterprise standard. Other IAM and Cyber organizations may adopt the portable controls and adapt local choices.

**Conclusion:** preserve the repository mechanics, but revise its vocabulary, authority statements, ownership boundaries, example framing, and navigation before calling it aligned with the white paper.

## Alignment summary

| Area | Assessment | Reason |
| --- | --- | --- |
| Product-to-Engineering bridge | Partial | Product and Engineering responsibilities are present indirectly, but the opening narrative centers people and agents rather than the bridge. |
| L0 through L3 organizational hierarchy | Not aligned | The repository uses L0 through L6 for artifact stages. |
| Delivery artifact chain | Strong mechanics, incorrect labels | The chain is useful and implemented, but it is conflated with organizational scope. |
| Access Management reference implementation | Not aligned | The repository is presented as a general template and approved standard. |
| Human decision ownership | Partial | H, C, and A exist, but some Product and Engineering decisions are assigned to A. |
| Gates | Partial | Gates 1 through 3 are close to the paper, but Gate 0 conflicts with the paper's three formal gates and enforcement is not scope-aware. |
| Traceability and change control | Strong foundation, partial policy alignment | Stable IDs and structural checks are useful; the checker does not cover the full artifact chain and its evidence states need refinement. |
| Adoption by other IAM and Cyber organizations | Partial | Portability exists technically, but portable controls are not separated clearly from local implementation choices. |
| Executive, Product, and Engineering readability | Partial | The README is optimized for implementers and agent users rather than the three intended audiences. |
| Pilot boundaries and open decisions | Not aligned | The sample can be mistaken for the chosen Access Management pilot scope, and several governance choices appear settled when the paper leaves them open. |

## Priority 0: resolve conceptual conflicts

### 1. Reserve L0 through L3 for organizational scope

The conflict appears in [README.md](/Users/bkh223/Documents/GitHub/sdd_framework/README.md:19), [docs/README.md](/Users/bkh223/Documents/GitHub/sdd_framework/docs/README.md:5), [framework-overview.md](/Users/bkh223/Documents/GitHub/sdd_framework/docs/guide/framework-overview.md:18), [spec-driven-development-v1.md](/Users/bkh223/Documents/GitHub/sdd_framework/docs/standards/spec-driven-development-v1.md:27), the diagrams, scaffolds, and the document-map generator at [tools/sdd/docs.mjs](/Users/bkh223/Documents/GitHub/sdd_framework/tools/sdd/docs.mjs:112).

Recommended change:

- Use L0 through L3 only for organizational scope.
- Rename the current document sequence to **delivery artifact chain**, with artifact types such as strategic direction, domain translation, Product specification, high level design, low level design, plans, code, tests, handoff, and evidence.
- Remove L4 through L6. Do not replace them with another L-number sequence.
- Add: "Gate 1, Gate 2, and Gate 3 are approval checkpoints. They do not correspond to organizational scope levels L1, L2, and L3."
- Update the generator, scaffolds, diagrams, templates, and checks in the same change so regenerated content cannot restore the old labels.

### 2. Reposition the repository and its authority

[README.md](/Users/bkh223/Documents/GitHub/sdd_framework/README.md:5) describes a generic AI-agent template. [AGENTS.md](/Users/bkh223/Documents/GitHub/sdd_framework/AGENTS.md:3) calls itself the repository constitution, and [spec-driven-development-v1.md](/Users/bkh223/Documents/GitHub/sdd_framework/docs/standards/spec-driven-development-v1.md:10) presents the standard as normative without limiting its scope.

Recommended change:

- State that Access Management is the example L1 domain under Cyber IAM where this reference implementation is being built and iterated.
- State that the implementation is not yet an enterprise standard.
- Explain that other IAM and Cyber organizations may adopt the portable core and adapt their governance, tools, roles, paths, and workflow.
- If the standard remains `approved`, define that status as approved for this repository or reference implementation.
- Describe `AGENTS.md` as a repository instruction adapter that points to the controlled standard, scope map, and artifact index. Do not make it the organizational authority by itself.

### 3. Make the Product-to-Engineering bridge the lead narrative

The current opening at [README.md](/Users/bkh223/Documents/GitHub/sdd_framework/README.md:7) says that people write intent and agents derive the rest. [framework-overview.md](/Users/bkh223/Documents/GitHub/sdd_framework/docs/guide/framework-overview.md:3) also begins with agent-related problems. This understates the ongoing work between Product and Engineering.

Recommended change:

- Product owns the problem, desired outcomes, scope, priorities, constraints, and acceptance.
- Engineering contributes feasibility, dependency, and risk input while intent is formed, then owns architecture and implementation choices.
- Product remains accountable when implementation reveals a choice that changes approved behavior or outcomes.
- Agents prepare bounded, traceable material from approved inputs. They do not replace accountable decisions.

### 4. Reconcile Gate 0 with the three formal gates

Gate 0 appears in [README.md](/Users/bkh223/Documents/GitHub/sdd_framework/README.md:25), [AGENTS.md](/Users/bkh223/Documents/GitHub/sdd_framework/AGENTS.md:24), the usage guide, templates, and skills. The paper treats intake as a human activity outside its three formal gates.

Recommended change:

- Rename Gate 0 to **intake approval**, **problem-framing approval**, or **intake checkpoint**.
- Retain Gate 1 for Product specification, Gate 2 for high level design, and Gate 3 for low level design.
- State explicitly that gates and organizational scope levels are independent.

### 5. Make gate enforcement scope-aware and artifact-specific

The gate hook at [gate.mjs](/Users/bkh223/Documents/GitHub/sdd_framework/tools/hooks/gate.mjs:12) looks for document types. It permits progression when any latest document of an expected type is approved. It does not confirm that the approval applies to the capability, application, software component, requirement set, or work item being advanced. It also does not verify the approver's authority, approval date, artifact version, unresolved items, or exception record. For `sdd-implement`, any non-superseded plan satisfies the hook even though the message says its LLD must be approved.

Recommended change:

- Bind each gate record to the exact governed artifact versions and organizational scopes.
- At Gate 1, require the named Product authority and required feasibility or control reviewers.
- At Gate 2, require the named Engineering authority and Product confirmation of any effect on approved outcomes or behavior.
- At Gate 3, require the affected Business Application, software component, and control authorities for the decisions within their scope.
- Validate approver role, date, version, open items, exceptions, and linked inputs.
- Make the implementation gate verify the plan and the specific approved design on which that plan depends.

### 6. Separate planned verification from delivered evidence

[trace-check.mjs](/Users/bkh223/Documents/GitHub/sdd_framework/tools/trace-check/trace-check.mjs:46) fails an approved acceptance criterion that has no test annotation. Both the high level and low level design workflows run the full check before implementation is expected to exist. A new Product specification can therefore pass Gate 1 and immediately block design work because its tests have not been written.

The current status `covered` also means that a test annotation exists. It does not mean the test passed or that the criterion is semantically satisfied.

Recommended change:

- Before build, require an approved test strategy with a criterion-to-planned-evidence mapping.
- During build, distinguish planned, linked, passing, failing, deferred, excepted, and drifted states.
- At handoff, require the applicable test links, execution results, and review evidence.
- Rename the current `covered` state to `test linked` until execution results are included.
- Keep the approved test strategy separate from the generated coverage and execution report.

### 7. Decide the criterion identifier syntax

The white paper's implementation example uses `AM-PRIV-001-AC1` and `AM-PRIV-001-AC2`. The repository parser at [sdd-lib.mjs](/Users/bkh223/Documents/GitHub/sdd_framework/tools/lib/sdd-lib.mjs:14) recognizes criteria in the simpler `<PREFIX>-<number>` form, such as `IAM-2`. The richer white-paper identifier would not be collected as a criterion, so an `@spec` reference to it would be reported as an orphan.

Choose one rule before describing the paper and repository as one implementation:

- Retain the white paper syntax and update the parser, schema, templates, scaffolds, checks, and tests.
- Retain the repository syntax and revise the paper's implementation-profile example, while keeping richer identifiers as a portable option.

The choice should preserve stable IDs without encoding organizational scope.

### 8. Correct the drift rule

[README.md](/Users/bkh223/Documents/GitHub/sdd_framework/README.md:32) directs teams to fix the specification first. [AGENTS.md](/Users/bkh223/Documents/GitHub/sdd_framework/AGENTS.md:27) is closer, but still relies on the repository's ambiguous use of layers.

Recommended wording:

> Verification reports a disagreement. The named human owner determines the first artifact in the delivery trace that no longer reflects approved intent. The team corrects that artifact, then updates or regenerates its dependent artifacts.

This permits a code-first correction when code violates unchanged approved intent, while sending a flawed requirement or design back to its accountable owner.

## Priority 1: align ownership, traceability, and examples

### 9. Add separate scope and trace metadata

The standard's front matter at [spec-driven-development-v1.md](/Users/bkh223/Documents/GitHub/sdd_framework/docs/standards/spec-driven-development-v1.md:118) does not carry the organizational scope model, and [spec-lint.mjs](/Users/bkh223/Documents/GitHub/sdd_framework/tools/spec-lint/spec-lint.mjs:16) only requires basic document metadata.

Add:

- `scope_level`
- `scope_name`
- `scope_parent`
- `artifact_type`
- `derives_from`
- `satisfies`
- `affected_scopes`

Document that a scope parent and a trace parent are different relationships. Add a separate scope map and artifact index rather than overloading one `parent` field.

### 10. Align H, C, and A with decision authority

The labels are useful, but several assignments are too broad. The component PRD template assigns functional requirements and acceptance criteria to A at [PRD-component-template.md](/Users/bkh223/Documents/GitHub/sdd_framework/docs/templates/PRD-component-template.md:119). The test strategy is A at [test-plan-template.md](/Users/bkh223/Documents/GitHub/sdd_framework/docs/templates/test-plan-template.md:14), and the LLD template describes consequential contracts as predominantly agent-written.

Use these boundaries:

- **H, Human decision:** a person supplies and approves the content. An agent may interview, organize, and edit it.
- **C, Human decision with agent draft:** an agent may draft options and expose assumptions, sources, and tradeoffs. A person selects and approves.
- **A, Agent prepared from approved inputs:** an agent may prepare the output, but it cannot change approved intent and must pass defined checks.

Functional requirements, acceptance criteria, approved test strategy, public contracts, schema decisions, and authorization enforcement choices should normally be C. Coverage status can remain A because it is derived evidence.

### 11. Complete the identifier lifecycle

The repository says identifiers are never renumbered or reused, but [spec-driven-development-v1.md](/Users/bkh223/Documents/GitHub/sdd_framework/docs/standards/spec-driven-development-v1.md:93) does not define when behavior changes require a new identifier. The implementation also selects the latest approved version and newest draft when collecting definitions. It cannot detect all reuse or meaning changes across older versions.

Add these rules:

- Editorial clarification keeps the identifier.
- A change to actor, trigger, response, measurable target, control obligation, or test obligation creates a new identifier with a supersession link.
- Splits and merges create new identifiers.
- Moving unchanged behavior between organizational scopes does not by itself create a new identifier.
- Identifiers should not encode organizational scope.
- Maintain an identifier history across document versions so removal, reuse, split, merge, withdrawal, and supersession can be checked.

### 12. Mark the current example as synthetic mechanics

The example at [README.md](/Users/bkh223/Documents/GitHub/sdd_framework/README.md:54) begins at `FR-3` and uses `iam` and `billing` as component names. Readers may mistake those names for L1 or L2 organizational selections.

Add this disclaimer at the README and example entry points:

> This is a synthetic mechanics example. The `iam` and `billing` names identify software components in the sample application, not L1 or L2 organizational scopes. They do not select the Access Management pilot's L2 capability or L3 Business Application.

Before the technical trace, show the full path:

`L0 Cyber and Cyber IAM direction -> L1 Access Management domain outcome -> illustrative L2 capability -> unnamed L3 Business Application -> tests, code, evidence, and outcome reporting`

Keep the L2 example and L3 application explicitly illustrative until the pilot owners select them.

### 13. Separate Product priority from operational severity

The combined queue is a core rule at [README.md](/Users/bkh223/Documents/GitHub/sdd_framework/README.md:46) and in the standard. The paper treats Product priority and operational severity as separate lenses. A merged queue is a local implementation choice.

Recommended wording:

> Product priority and operational severity are separate decision lenses. The Access Management reference implementation may test a combined ordering rule, but the portable SDD core does not require one queue. Adopting organizations map both lenses into their existing portfolio and incident processes.

### 14. Narrow and extend the traceability claim

The README header and opening claim that every line of behavior is linked. The checks actually verify PRD criterion definitions, tests, and annotated behavior entry points. They do not yet validate the full path through L0 direction, L1 translation, L2 and L3 design, architecture decisions, tasks, handoff, and outcome evidence. This is a useful foundation, but a narrower one.

Recommended wording:

> Checks verify that approved criteria resolve to cited tests and behavior entry points. They flag broken or missing structural links. They do not prove semantic equivalence or coverage of every line, so accountable human review remains required.

Add adjacent-artifact checks after the artifact index and scope metadata are approved. Until then, describe wider end-to-end traceability as planned. Also qualify the README's claim that the framework works with Codex and other agents. The current gate and approved-file protection hooks are Claude-specific; other agents follow the controls procedurally unless equivalent adapters are installed.

### 15. Strengthen audit evidence

The trace index at [docs/trace/index.yaml](/Users/bkh223/Documents/GitHub/sdd_framework/docs/trace/index.yaml:1) records useful component status, but it does not identify organizational scope, audit owner, or the governed artifact versions. The example also has no audited commit. Staleness checks inspect configured source paths, not changes to linked Product or design artifacts.

Record the audited scope, relevant artifact versions, commit, findings, owner, disposition, and next action. Mark evidence stale when a linked upstream artifact changes, not only when source files change.

## Priority 2: improve navigation and documentation integrity

### 16. Replace the document map with three explicit views

[docs/README.md](/Users/bkh223/Documents/GitHub/sdd_framework/docs/README.md:1) currently mixes organizational meaning, document location, ownership, and approval.

Present three separate views:

1. **Organizational scope map:** L0 through L3 names, parents, owners, and status.
2. **Delivery artifact index:** artifact type, scope, upstream source, owner, version, status, and downstream relationships.
3. **Approval workflow:** Gate 1 through Gate 3 plus intake, code review, security review, and exceptions.

Update the document-map generator rather than editing only its generated table.

### 17. Add audience routes

The README navigation is implementation-centered. Add **Start by audience** above Quick start:

- **Executives:** value hypothesis, scope hierarchy, pilot measures, risks, and open decisions.
- **Product Managers:** source direction, domain translation, seed questions, Product specification, acceptance, and Gate 1.
- **Engineering and Security:** feasibility, design authority, scope metadata, trace checks, change control, and evidence.
- **IAM and Cyber adopters:** portable core, adaptable choices, pilot sequence, exceptions, and adoption criteria.

### 18. Expand the glossary and diagrams

[docs/glossary.md](/Users/bkh223/Documents/GitHub/sdd_framework/docs/glossary.md:1) needs Access Management, L0 through L3, organizational scope hierarchy, delivery artifact chain, Business Application, software component, strategy, declaration, imperative, HLD, LLD, agent role, drift, and traceability. State that HLD and LLD are artifact types, not organizational levels.

Update both SVG diagrams and their alternative text. The current header repeats the overly broad statement about every line of code, and the document-stack diagram encodes the conflicting L0 through L6 model.

### 19. Fix or formally account for documentation integrity findings

A deterministic documentation audit found five integrity issues:

- `docs/adr/` has no canonical `README.md` index.
- Three links in `tools/sdd/scaffold/AGENTS.md` are not valid at their source location.
- The coverage link in `tools/sdd/scaffold/test-plan-v1.md` is not valid at its source location.

The scaffold links may be intended to resolve only after installation. If so, document that relocation rule and validate the rendered scaffold instead of treating source-relative links as ordinary links. Otherwise, use source-valid placeholders or paths. Also link the sample postmortem from an operations or history index so it is not an orphan.

The audit also reported optional governance files as absent. Do not create empty shells merely to silence warnings. Reuse the existing standard, artifact index, trace report, and changelog where they already provide the required authority or evidence.

### 20. Address adoption licensing

[README.md](/Users/bkh223/Documents/GitHub/sdd_framework/README.md:162) states that no license has been chosen. That conflicts with encouraging reuse by other IAM and Cyber organizations. Select and publish an approved license before wider distribution.

## Recommended README opening

> SDD creates a controlled bridge from Product intent to Engineering delivery. Product owns the problem, outcomes, scope, priorities, constraints, and acceptance. Engineering contributes feasibility and risk input as intent is formed, then owns architecture and implementation choices. Shared templates, named decision ownership, approval gates, and traceable identifiers preserve that connection through tests, code, evidence, and outcome reporting.
>
> Access Management is the example L1 domain under Cyber IAM where this reference implementation is being built and iterated. It demonstrates how L0 Cyber and Cyber IAM strategy, declarations, and imperatives can be translated into L2 capability definition and L3 Business Application delivery. The worked example is synthetic and does not select the pilot capability or application.
>
> This repository is a reference implementation, not a finished enterprise standard. Other IAM and Cyber organizations may adopt the portable core, including standard templates, human decision ownership, approval gates, traceability, and change control, while adapting tools, paths, roles, and workflow to their governance.
>
> Agents support the workflow by preparing bounded, traceable material from approved inputs. They do not replace accountable Product, Engineering, Security, or business decisions.

## Recommended changes to the white paper

The white paper should remain the conceptual source for this alignment. Only limited additions are recommended:

1. In Section 10, link the repository as the current Access Management reference implementation and identify a tagged release or reviewed commit.
2. Add an implementation-status note that the current repository still uses legacy artifact-stage L labels and is being migrated to the L0 through L3 organizational model.
3. Clarify that the repository's intake checkpoint and combined queue are local implementation experiments, not portable-core requirements.
4. State that the present structural checker covers PRD criteria, tests, and code annotations. The broader artifact chain remains planned.
5. Resolve the `AM-PRIV-001-AC1` versus `IAM-2` identifier mismatch or label the former as a target syntax not yet implemented.
6. Note that current automated gates are document-type checks and do not yet enforce the full scope and authority model.
7. Record the repository's controlled-standard location as open until the owning authority approves it. Do not allow `AGENTS.md`, a README, or a tool configuration to become organizational authority by implication.

These additions make the paper honest about the implementation's current state without weakening its target model.

## Recommended implementation sequence

1. Approve the vocabulary decision: organizational L0 through L3, unnumbered delivery artifact chain, and independent Gate 1 through Gate 3.
2. Update the controlled standard, authority statement, glossary, and ownership rules.
3. Update the README, framework overview, usage guidance, `AGENTS.md`, and example disclaimers.
4. Update templates, front matter, scaffolds, diagrams, the document-map generator, lint rules, and related tests.
5. Make gates scope-aware and split planned test evidence from delivered verification results.
6. Add the synthetic scope-to-delivery trace and leave the actual pilot L2 and L3 unresolved until owners decide.
7. Extend trace checks across adjacent artifacts and strengthen audit records.
8. Regenerate documentation and run all checks.
9. Tag the first aligned reference-implementation release and cite that release from the white paper.

## Validation performed

- Local `HEAD`, local `origin/main`, and GitHub `refs/heads/main` all resolved to `6d7e15ee9a946381cd213fd9cf26a08e50fb8311`.
- The local branch was clean.
- `node tools/sdd/cli.mjs check` completed with zero specification-lint errors, zero specification-lint warnings, and zero trace-check errors.
- Trace check reported one warning: the draft `billing` component has never been audited. Its three criteria do not yet have tests, which the tool reports as informational because the PRD is draft.
- Annotation reach reported 100 percent for the two source files currently in scope.
- These results show internal consistency with the repository's present rules. They do not test the white paper controls identified in this report.
- The full documentation-governance audit found the five link and ADR-index issues described above.
- The full test and type-check suites were not executed because the development dependencies are not installed. No installation or repository mutation was performed for this analysis.

## Decisions required before implementation

The following choices should remain explicit rather than being inferred during editing:

- Whether the repository itself is the Access Management reference implementation or a generic toolkit that contains an Access Management profile.
- The authoritative controlled standard and its approving owner.
- The actual Access Management pilot L2 capability and L3 Business Application.
- Whether the intake checkpoint remains as a named local control.
- Whether a combined priority and severity queue will be tested locally.
- The canonical criterion ID syntax and its migration rule.
- The evidence states required before build, handoff, and release.
- Gate approvers, exception authority, fast-path criteria, and audit timing.
- The license for reuse.

No repository or white-paper content was changed as part of this review.
