# Fennec X Code V1 — Official Development Roadmap

**Status:** APPROVED ROADMAP — PLANNING BASELINE ONLY  
**Roadmap date:** October 16, 2026  
**Repository:** https://github.com/naoufelbvb2-arch/fennec-x-code-v1  
**V0 accepted implementation:** `cf3eb5479f30afdc86d88f436bc6787f7c3dcfd3`  
**V0 final acceptance documentation commit:** `e8d9982b910c150aa5757becc3ea8084809035d9`  
**Next stage:** S01 — Cognitive Executive  
**Progress:** 0 of 8 V1 stages accepted

> Approval of this roadmap authorizes its documentation and use for planning. It does **not** approve a particular implementation design, permit source changes, or freeze unresolved V1 contracts. Every stage needs a separate specification, review, implementation authorization, and verification.

## 01. Purpose and development philosophy

V0 is an accepted and frozen **functional baseline** within the scope stated by `V0-FINAL-ACCEPTANCE-REPORT.md`. It has a working Agent Core, Model Gateway, Tool Runtime, Workspace & Context boundary, user-controlled write/command approvals, automated regressions, and limited live DeepSeek evidence.

V1 aims to extend that working foundation into a **cognitive software-engineering agent**: a system that can develop an evidence-grounded project model, select appropriate cognitive methods, reason about alternatives and consequences, plan and replan, execute safely, verify its work, resume ongoing projects, and recruit bounded temporary specialists when useful.

Follow **Build → Verify → Stabilize → Extend**. Each stage must yield a working, testable increment. Prefer the smallest architecture that demonstrates measurable value; do not add frameworks solely because an expert-human analogy suggests them.

Research and design input comes from the separate `naoufelbvb2-arch/ai-coding-agent` repository, including FCA v1.0.1 and source-backed RDMS studies. Those documents are reference material, **not automatically imported runtime specifications**. Its L0–L7 consolidated architecture is still under review with unresolved mapping/approval questions. Do not blindly transplant it into Fennec.

## 02. Accepted V1 direction and architectural boundaries

The accepted design direction is a **hybrid cognitive architecture** with a Cognitive Executive **above and separate from** the frozen V0 Agent Core.

- **Cognitive Executive:** Coordinates goals, stages, skill/capability selection, cognitive decisions, ongoing task state, and delegation.
- **Agent Core V0:** Remains the proven bounded execution engine, invoked through explicit, reviewed integration boundaries. Do not silently broaden its authority.
- **Model Gateway:** Retains user-selected LLM/provider configuration; the reasoning provider is replaceable and does not own agent identity or tool authority.
- **Tool Runtime + Workspace & Context:** Retain filesystem/command boundaries, per-operation permissions, safety limits, and real execution evidence.
- **Cognitive Runtime / Capabilities:** Provide testable reasoning functions (e.g., modeling, simulation, causal analysis), not necessarily one LLM call per function.
- **Skill Registry & Router:** Discover and select approved, versioned methodologies with typed inputs, outputs, prerequisites and permissions. A skill is not automatically executable code or authority.
- **World Model:** A structured, queryable model (initially a small typed graph) of project components, relationships, dependencies, provenance, epistemic status and freshness; not a second source of truth.
- **Working State:** Maintains current focus, goals, hypotheses, plans and pending needs from the beginning. Durable recovery and long-term experience memory are introduced deliberately later.
- **Temporary Specialists:** Optional bounded workers, controlled by a single canonical coordinating authority; never mandatory for every task.

The above defines **separation of concerns and development intent**, not frozen class names, storage engines, process topology, or API signatures. Exact ownership, lifecycle and schemas are S01/S02 design-review questions.

### Evidence and authority principles

1. LLM output is a proposal, not proof of an external fact or an authorization to act.
2. Actual file contents, repository state, command/test observations and their provenance ground claims about reality.
3. Distinguish **observed facts, assumptions, hypotheses, unknowns, predictions**, and **stale information**; an observed fact can become outdated without becoming false history.
4. A World Model assertion must carry appropriate evidence or be explicitly marked unverified; its dependencies govern freshness.
5. Skills and Specialists cannot write canonical shared state, grant permissions or bypass Tool Runtime simply by returning convincing text.
6. One coordinating Executive is the intended semantic authority; legal, technical and user-approval gates remain separate and non-bypassable.
7. Predictive mental simulation and actual executable experiments are distinct; compare predictions with independently captured results.
8. Keep components independently replaceable and test failures/limitations explicit.

## 03. Eight-stage construction roadmap

Stage order describes **primary delivery and acceptance gates**. Some responsibilities have early minimum forms and become fuller later: S01 introduces minimal working state; S02 matures the project model; S06 adds durability, resumption and long-term memory. Do not implement an entire future stage prematurely.

| Stage | Name | Primary outcome | Status |
| --- | --- | --- | --- |
| S01 | Cognitive Executive | A separate coordinator uses V0 safely through a reviewed adapter | NEXT — NOT STARTED |
| S02 | World Model | Queryable, evidence-grounded graph with dependency freshness | PLANNED |
| S03 | Cognitive Skills | Bounded, versioned skill registry/router and first tested skills | PLANNED |
| S04 | Reasoning & Mental Simulation | Explicit hypotheses, predictions, causal checks and uncertainty | PLANNED |
| S05 | Planning, Execution & Review | Adaptive hierarchical plans, execution feedback and critique | PLANNED |
| S06 | Memory & Recovery | Durable task continuity, governed experience and safe resumption | PLANNED |
| S07 | Temporary Specialists | Optional scoped multi-worker delegation and lawful integration | PLANNED |
| S08 | Final Integration & Acceptance | Cross-stage regression, realistic evaluation and V1 freeze | PLANNED |

### S01 — Cognitive Executive

**Objective:** Build the smallest independent Cognitive Executive capable of coordinating one task without rewriting or replacing V0.

**Scope:** Explicit task/goal lifecycle, minimal working state, a bounded decision loop, typed requests/results through a narrow V0 adapter, error/cancellation propagation, and authority/permission preservation. Define what belongs to Executive vs Agent Core vs future Skill Router and World Model. Avoid speculative orchestration frameworks.

**Acceptance gate:** A representative task is received, managed through observable states, delegated to V0, and reported accurately; denial, failure, budget exhaustion and cancellation cannot be hidden or bypassed. V0 behavior/tests remain intact.

### S02 — World Model

**Objective:** Maintain a structured, inspectable project mental model rather than repeatedly regenerating narrative summaries.

**Scope:** Typed nodes/edges for files, symbols, components, boundaries, dependencies and relevant decisions; source references, uncertainty categories, version/dependency stamps, query/update rules and targeted invalidation. Begin with a small practical representation; do not assume a graph database is required.

**Acceptance gate:** Model a small real codebase, answer relationship questions from the model with traceable evidence, then change a relevant source file and detect/reassess affected assertions. Compare against V0/no-model behavior.

### S03 — Cognitive Skills

**Objective:** Add approved, discoverable cognitive/engineering methods without coupling them to Executive internals.

**Scope:** Skill contracts, registry, selection/router, permissions and validation, versioning and failure handling. Initial candidate methods: requirements analysis, mental-model construction, chunking/abstraction, information-gap discovery, and skill selection. The proposed `Find Skills` behavior is part of controlled routing, not authority to install arbitrary skills.

**Acceptance gate:** For known tasks the router chooses suitable enabled skills, validates output, handles absent/disabled/failing skills, and supports skill replacement without breaking unrelated functions or V0.

### S04 — Reasoning & Mental Simulation

**Objective:** Strengthen engineering judgment before edits while separating prediction from observation.

**Scope:** Causal hypotheses, alternatives, edge-case predictions, bounded dry-run reasoning, risk/uncertainty tracking, and actual experiments when appropriate and authorized. Evaluate an optional LLM-guidance strategy (`Grille LLM`) by measured quality/cost, not by its name.

**Acceptance gate:** On selected seeded defects or design changes, produce falsifiable predictions, run authorized discriminating checks, record mismatches and corrections, and demonstrate a defensible improvement or limitation against a simpler baseline.

### S05 — Hierarchical Planning, Execution & Review

**Objective:** Join cognition to real engineering delivery.

**Scope:** Goals → stages → tasks → steps; dependencies and completion evidence, replanning after contradictory observations, bounded V0 tool execution, reviews of behavior, structure and requirements, and separation of self-critique from independently observed verification. Required new tool capabilities, if any, need separate safety/contract review rather than silent expansion of V0.

**Acceptance gate:** Complete a small multi-step coding project with explicit plans, permitted file changes, real tests, a demonstrated replan on failure, and a final evidence-backed review against user requirements.

### S06 — Memory & Recovery

**Objective:** Preserve project/task continuity beyond a single process and learn carefully from verified experience.

**Scope:** Durable checkpoints, task/decision/evidence history, interruption and recovery protocol, dependency revalidation before resumed actions, and later long-term episodic/semantic experience with a governed proposal/learning gate. Early S01 working state is not equivalent to trusted long-term memory.

**Acceptance gate:** Interrupt a genuine task, restart later, restore only the supported state, detect relevant changes, and resume safely without automatically repeating potentially effective actions. Demonstrate that unverified LLM interpretations are not promoted to canonical facts.

### S07 — Temporary Specialists

**Objective:** Allow one persistent Executive to form a bounded temporary engineering team only where useful.

**Scope:** Delegation policy, scoped specialist contracts, separated workspaces/context, budgets, independent review opportunities, provenance of specialist outputs, conflict detection, controlled result adoption and shutdown. Shared-world mutation remains under original approval and action gates.

**Acceptance gate:** On a suitable decomposable project, coordinate multiple specialists, reconcile outputs and detect conflicting proposals without authority confusion or unsanctioned workspace effects; measure whether delegation beats a single-agent baseline on quality, cost or time.

### S08 — Final Integration & Acceptance

**Objective:** Establish reliable evidence for V1 within a declared supported scope, then document and freeze an approved V1 baseline.

**Scope:** Cross-stage integration, safety/regression suites, model/tool failures, state freshness and recovery, authorization attacks, conflicting outputs, realistic project tasks, latency/token/cost assessment, and known-limitations review. Avoid unrelated new features during final stabilization.

**Acceptance gate:** Predeclared functional and safety criteria are satisfied; all applicable V0 and V1 regression suites pass; supported provider/project scope and limitations are explicit; independent code/evidence review and `V1-FINAL-ACCEPTANCE-REPORT.md` support an approved freeze.

## 04. Stage delivery and governance protocol

Apply the following sequence to **each** stage; a roadmap entry is not an authorization to skip any gate:

1. **Architecture Specification:** Define purpose, boundaries, state ownership, contracts, error/failure behavior, security and scope.
2. **Adversarial Design Review:** Resolve blocking ambiguity and compare a minimum viable design to alternatives; document remaining explicit assumptions.
3. **Authorized Implementation:** Implement the approved scope in an isolated Git branch; use Codex only under the stage-specific task.
4. **Verification & Evaluation:** Run focused unit/integration/security tests, V0 regressions and a realistic capability experiment against acceptance criteria.
5. **Independent Review & Promotion:** Inspect the actual changed source, tests and evidence, authorize promotion, and record final SHA plus known limits. Mark the stage ACCEPTED only then.

A large stage MAY be divided into substeps/experiments. Do not declare the overall stage accepted until its gate is satisfied. If an experiment fails, preserve findings and revise only with explicit review.

**Progress vocabulary:** PLANNED → SPECIFICATION → REVIEW → IMPLEMENTATION → VERIFICATION → ACCEPTED; BLOCKED may apply at any nonterminal step. The authoritative Git history and stage reports, not status text alone, provide acceptance evidence.

## 05. Preservation and change-control rules

- V0 is frozen as a **traceable baseline**, not an assertion that all its files can never be changed in future approved versions.
- Do not modify V0 contracts, permission handling or architectural specifications incidentally. Any unavoidable extension requires a dedicated compatibility/security review, tests and explicit authorization.
- New V1 modules should interact through narrow, documented interfaces; dependency direction and ownership must be justified, not inferred from a diagram.
- Every learned/asserted representation needs an explicit trust boundary; retrieved memory or specialist text is advisory until current-context acceptance.
- Do not equate a successful LLM response with a successful tool action; record and inspect execution evidence.
- Avoid mandatory LLM calls at every stage; use deterministic code for structure, validation, bookkeeping, routing and freshness when appropriate.
- Do not enable unrestricted shell access or assume that trusted-project mode is an OS sandbox.
- Prefer a single Executive with optional workers over autonomous competing authorities.
- Measure value and overhead before retaining complex cognitive machinery.
- Every stage documents rollback or disablement of its new capabilities, insofar as technically practical.

## 06. Evaluation framework

For each new capability, specify the relevant measurable indicators **before** evaluation, for example:

- **Correctness:** evidence-supported answers, tool outcomes, test passes, requirement coverage.
- **Model quality:** accurate component/dependency links, stale-link detection and uncertainty calibration.
- **Reasoning:** predictions confirmed/refuted by independent observations, defect localization, unnecessary edit rate.
- **Planning:** dependency accuracy, completed/verified slices, appropriate replanning and error recovery.
- **Safety:** approval compliance, scope isolation, denied-action behavior, crash/restart uncertainty preservation.
- **Efficiency:** LLM calls, tokens/cost where available, elapsed time, repeated exploration, specialist overhead.

No fixed improvement percentages or universal benchmark claims are approved by this roadmap. Select concrete fixtures, sample sizes, baselines and success thresholds in each stage specification.

## 07. Initial repository tracking state

| Record | Value |
| --- | --- |
| Roadmap | Approved as planning direction |
| V0 implementation baseline | `cf3eb5479f30afdc86d88f436bc6787f7c3dcfd3` |
| V0 acceptance report | `V0-FINAL-ACCEPTANCE-REPORT.md` |
| Current accepted V1 stages | 0 / 8 |
| Next authorized *design topic* | S01 — Cognitive Executive architecture |
| V1 production implementation authorization | NOT GRANTED |
| V1 architecture freeze | NOT GRANTED |
| Final V1 acceptance | PENDING |

The current roadmap should be updated through separately reviewed documentation commits as stages advance. Any reordering, removal or major scope change requires an explicit roadmap decision with rationale; do not rewrite historical acceptance evidence.

## 08. Next action

Begin **S01 architecture and interface design**, without implementation. Resolve the minimum Cognitive Executive state machine, decision authority, its adapter to Agent Core V0, failure semantics, and a testable acceptance fixture. Consult the previous AI Coding Agent research for useful obligations while avoiding automatic import of its unresolved or unimplemented designs.

**End of V1 Roadmap.**
