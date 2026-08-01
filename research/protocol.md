# ContractCapsule Research Protocol

Protocol ID: `CCS-FSE27-M1-G0-candidate-2026-08-01`

Status: M1 protocol candidate frozen for G0 author review. M0 closed by human
approval on 2026-08-01. No M2-M11 work or full experiment is authorized by
this document. After G0 approval, changes require a dated amendment that states
the reason, affected outcomes, and whether any pilot or full-study data existed
when the change was made. The prior version remains auditable.

## Normative Inputs

- `docs/spec/CCS-2.1.md`
  - SHA-256: `aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c`
- `docs/superpowers/plans/2026-07-30-contract-capsule-fse-2027-execution-plan.md`
  - SHA-256: `7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0`
- `docs/protocol/formal-model.md`
- `docs/protocol/failure-semantics.md`
- `AGENTS.md` governs daily execution beneath the two frozen baselines.

Execution status belongs in `research/decision-log.md` and module reports. The
two frozen baselines are never edited in place.

## Submission and Governance Constraints

The confirmed target is FSE 2027 Research Papers. Per the frozen plan's
official-source lock dated 2026-07-30:

- initial submissions allow at most 18 pages of text and figures plus 4 pages
  of references;
- the anonymous review class is
  `\documentclass[acmsmall,screen,review,anonymous]{acmart}`;
- review is heavy double-anonymous;
- a Data Availability statement follows the conclusion;
- an anonymized replication package is expected when possible; and
- AI use affecting design, implementation, datasets, experiments, analysis,
  validation, or artifacts is disclosed in Methods.

Tracked public research files record author-gate approval but no identifying
author details. Codex is a research tool, not an author. Authors remain
accountable for claims, data, citations, conflicts, ethics, anonymity, and the
submission.

## Thesis and Contribution Boundary

The thesis is that coding-agent project context can be represented as
immutable, source-grounded, contract-bearing replacement units whose
task-specific views and behavioral substitutions can be audited and validated.

The paper does not claim novelty for typed atoms, compression, retrieval,
provenance, memory tiers, packaging, Skill, MCP, or agent integration alone.
The C1 novelty candidate is their composition around replacement correctness:

```text
old capsule --evidence + closure + behavioral contract--> new capsule
```

Success requires target effects, protected invariants, controlled forbidden
spillover, mandatory closure, evidence traceability, atomic activation, and a
recoverable prior reference. C2-C5 retain explicit missing-evidence status in
`research/claim-evidence-matrix.md`.

## Research Questions

### RQ1: Task Effectiveness and Efficiency

Does ContractCapsule improve or preserve coding-task success while reducing
irrelevant context compared with native context, full-context injection, RAG,
summary compression, and atom-only context?

Primary outcomes:

- repository test pass rate;
- replacement-contract test pass rate;
- task completion rate;
- mandatory-constraint adherence rate; and
- input tokens under the common context accounting rule.

Secondary outcomes:

- cached input tokens when the provider reports them;
- wall-clock duration;
- reported provider cost; and
- failure category distribution.

No single effectiveness/cost composite replaces the individual outcomes.

### RQ2: Explainability and Evidence Fidelity

Can an auditor determine which context influenced a task and resolve it to the
corresponding source evidence?

Primary outcomes:

- critical-atom recall;
- provenance resolution rate;
- source-span correctness; and
- exact-source expansion success rate.

Secondary outcomes:

- gold-atom selection precision and recall;
- View Manifest decision completeness; and
- stale-source detection rate.

### RQ3: Replacement Correctness and Safety

Does ContractCapsule replace project context with fewer unintended behavioral
changes than competing representations?

Primary outcomes, always reported separately:

- Target Effect Realization (`TER`);
- Protected Invariant Preservation (`PIP`); and
- Behavioral Spillover Rate (`BSR`).

For run `r`, TER and PIP are passed/required check fractions and BSR is
triggered/forbidden-probe fraction. CapsuleBench check sets are non-empty.
Gate-level replacement success requires `TER=1`, `PIP=1`, and `BSR=0`.

Secondary outcomes:

- mandatory dependency-closure success;
- conflict-detection rate;
- unsafe activation rate; and
- rollback success rate.

`RCS = TER * PIP * (1 - BSR)` is descriptive only and cannot replace or mask a
component.

### RQ4: Generality and Component Necessity

Do results generalize across coding agents, and which CCS-2.1 mechanisms are
necessary?

Primary outcomes:

- direction and magnitude of CC-versus-baseline effects on the preregistered
  RQ1 and RQ3 outcomes in the stratified Claude Code replication; and
- change in TER, PIP, and BSR for each preregistered ablation relative to full
  ContractCapsule.

Secondary outcomes:

- outcomes split by task category, language, repository, and risk; and
- RQ2 changes under source-map and compression ablations.

These strata are descriptive unless sample sizes support the frozen paired
analysis; no new primary subgroup claim may be selected after observing data.

## Conditions and Ablations

All non-native conditions use the same maximum runtime-view budget. Setup and
task text are condition-isolated.

| ID | Condition | Context supplied |
|---|---|---|
| B0 | Native Agent | Repository and default agent context discovery only |
| B1 | Full Context | Complete authorized task documents within the common budget |
| B2 | RAG | Permission-filtered BM25 plus embedding top-k chunks |
| B3 | Summary | Source-grounded LLM summary within the common budget |
| B4 | Atom Only | Typed source-grounded atoms without closure, replacement contract, or swap controller |
| CC | ContractCapsule | Complete CCS-2.1 runtime path |

| ID | Ablation | Removed mechanism |
|---|---|---|
| A1 | No closure | Mandatory dependency closure |
| A2 | No contract | Behavioral replacement contract |
| A3 | No expansion | Source-map exact evidence expansion |
| A4 | Uniform compression | P0-P4 risk-aware compression |

## Planned Sample and Unit of Analysis

- Primary Codex study: 24 tasks x 6 conditions x 3 independent runs = 432.
- Claude Code replication: 12 stratified tasks x 6 conditions x 3 runs = 216.
- Ablation study: 12 stratified tasks x 5 CC/ablation conditions x 3 runs =
  180.
- Planned full total: 828 valid scheduled runs, excluding preflight and
  infrastructure-only attempts.

The experimental unit is one independently seeded task-condition-agent run.
For primary paired comparisons, repeated runs are first aggregated at the
task-condition-agent level. The task is the pairing and bootstrap cluster; a
run is not treated as an independent repository/task replicate.

The M8 pilot is separately labeled and is not pooled into confirmatory full
results unless an amendment approved before viewing full-study outcomes states
otherwise.

## Benchmark Inclusion Rules

CapsuleBench v1.0 targets 24 tasks from at least eight permissively licensed
public repositories and at least three language ecosystems. A task is included
only if:

- the repository license permits the planned use and redistribution;
- old/new context is recoverable from immutable commits;
- setup and execution can be isolated;
- target effects and protected invariants are objectively executable;
- no private or confidential data is used;
- no unavailable paid infrastructure is required;
- native setup/execution completes within 15 minutes; and
- checkout size is below 2 GiB.

The categories are policy/invariant migration, API/interface evolution,
architecture-decision replacement, and procedure/build/deployment convention
replacement. The task, commits, capsule digests, gold checks, and license
provenance are frozen at G2.

## Ground Truth and Human Review

- Codex may propose atoms, tests, labels, and explanations, but none is ground
  truth by itself.
- A human author verifies every task target effect and protected invariant
  against immutable source evidence.
- At least 25% of tasks receive an independent second human review.
- Disagreements and adjudications are retained in
  `benchmark/adjudication.jsonl`.
- Scorers are condition-blind and executable without an agent.
- Gold and scorer changes create a new benchmark version; the old digest stays
  available.

## Exclusion Rules

### Before Benchmark Freeze

A candidate task is excluded if any inclusion rule fails, source licensing is
ambiguous, old-state setup cannot be made deterministic, the behavioral truth
requires subjective intent rather than repository-observable behavior, or a
stable protected-invariant/target-effect split cannot be defined. The reason is
recorded for every screened candidate.

### After Benchmark Freeze

- No task or valid run is excluded because its result is unfavorable.
- A task-level defect discovered after G2 does not disappear silently: suspend
  it, publish a versioned protocol/benchmark amendment, retain all affected
  records, and report confirmatory analyses with and without the task only when
  the amendment justifies both.
- Primary analyses do not impute missing task-condition cells.
- Incomplete cells and their reasons are reported; G4 requires every scheduled
  cell or an explicit infrastructure-failure record.
- Provider fields unavailable by design are marked unavailable, not estimated.

## Failure and Retry Rules

A run is a valid outcome, not retryable, when the agent produces incorrect
code, violates a constraint, times out under the fixed task limit because of
its own behavior, exhausts its context budget, triggers a ContractCapsule
blocker, or otherwise fails the task in a functioning environment.

`infrastructure_failure=true` is permitted only for an external/provider
outage, runner or sandbox provisioning failure, dependency-registry outage
during deterministic setup, invalid provider response that prevents a model
turn from existing, or instrumentation failure that makes mandatory outcome
fields unavailable. The harness records category, timestamps, attempt ID, raw
events, and operator evidence.

- Only an attempt marked `infrastructure_failure=true` may be retried.
- At most two retries follow the initial infrastructure-failed attempt.
- Every attempt is retained; retry does not overwrite the original run ID.
- Retry uses the same frozen task, condition, agent/model configuration,
  budget, and prompt inputs; only infrastructure metadata and attempt ID vary.
- The first non-infrastructure outcome fills the scheduled cell and is never
  replaced by a later attempt.
- Exhausted infrastructure failures remain missing and are reported; they are
  not converted to task failures or silently rescheduled until favorable.

## Statistical Analysis Plan

All analysis is script-generated from checksum-verified raw records.

1. Aggregate three repeated runs to task-condition-agent summaries before the
   primary paired comparison.
2. Report each condition's raw run distribution and per-task distribution in
   addition to aggregates.
3. For paired binary task-level outcomes, report paired risk differences with
   task-cluster bootstrap 95% confidence intervals and use McNemar's exact test
   for the null paired difference.
4. For paired continuous, count, rate, token, time, cost, TER, PIP, and BSR
   summaries, report median and mean paired differences with task-cluster
   bootstrap 95% confidence intervals. The default null test is a two-sided
   paired permutation test over task-level differences.
5. A Wilcoxon signed-rank analysis may be reported only as a preregistered
   sensitivity analysis when at least ten non-zero task pairs exist and its
   ordinal/symmetry interpretation is stated. It never replaces the default
   because of a favorable p-value.
6. Apply Holm correction within each RQ family across CC-versus-baseline
   primary-outcome tests. Report unadjusted and adjusted values.
7. Report effect sizes and confidence intervals, not p-values alone.
8. Treat agent, condition, task, repository, language, category, and risk
   subgroup results as frozen stratified/descriptive analyses; do not promote a
   favorable subgroup to a new primary claim.
9. Keep infrastructure attempts outside outcome denominators but report their
   frequency by condition and agent.
10. Retain valid unfavorable runs and show failure categories.

The bootstrap uses tasks as clusters and a fixed seed recorded in the analysis
configuration. The number of bootstrap and permutation draws is frozen in M8
before the full experiment because runtime benchmarking is needed to select a
practical value; it may not be selected from outcome direction. Any deviation
is a visible amendment.

## Pilot and Protocol Change Rules

The M8 pilot may reveal implementation defects, systematic context leakage,
unstable gold tests, token-accounting errors, or unaffordable scope. Before G2,
the authors may repair defects or narrow secondary/cross-agent scope while
preserving RQ3 and the primary CC comparison. They may not change RQs,
conditions, primary outcomes, or exclusion definitions because the observed
direction is inconvenient.

G3 outcomes are proceed, narrow, or defer. Defer if contracts cannot be
operationalized, ground truth is unreliable, or no defensible atom-only
distinction remains.

## Data, Reproducibility, and Integrity

- Every planned cell has stable run and attempt IDs.
- An existing valid run ID is never overwritten.
- Raw events include repository commit, capsule digests, prompt digest, view
  manifest digest where applicable, agent/model/config versions, usage, exit
  code, and infrastructure status.
- Raw full-study data become read-only after G4 and receive checksums and a
  version tag. Corrections produce a new version without deleting the old one.
- Processed tables and figures are generated by scripts, never edited as the
  source of truth.
- Citation claims trace to primary papers, publisher pages, or official
  documentation. Unverified rows use `citation_verified=false`.
- The anonymous M11 package removes local identities and machine paths while
  retaining reproducible relative references and hashes.

## AI Use

AI assistance that affects design, implementation, benchmark construction,
experiments, analysis, figures, or conclusions is appended to
`research/ai-usage-ledger.jsonl`. Unavailable model or prompt metadata is
marked unavailable, never fabricated. Methods will disclose material use.
Human authors independently validate benchmark truth, citations, ethics,
statistics, and conclusions.

## Ethics Scope

The current protocol evaluates coding agents and publicly licensed code
repositories and does not collect human-participant data. Internal validation
of task labels by authors or collaborators is not research-subject data.
Adding user studies, interviews, surveys, private developer data, crowdsourced
labeling, or identifiable telemetry reopens the ethics gate and requires review
under the authors' institutional rules. This protocol record does not replace
an institution's legal or ethics determination.

## M0 Environment Lock

- uv 0.12.1 (`329541a50`, 2026-07-31, aarch64-apple-darwin).
- CPython 3.12.13.
- Project interpreter: `.venv/bin/python3`.

The original M0 absolute interpreter path remains in the M0 audit report and
must be removed or normalized from the anonymous M11 artifact.

## Human Decisions

| Decision | Status |
|---|---|
| Target track and both frozen digests | Confirmed by author, 2026-08-01 |
| Final author/affiliation gate | Confirmed; identity details outside tracked public files |
| Submission conflicts | Confirmed by author: no known submission conflicts |
| Current non-human-participant ethics scope | Confirmed by author; reopen triggers retained |
| M0 technical and governance exit gate | Approved and closed |
| M1 G0 novelty and protocol freeze | Pending author review |
| Repository license and citation metadata | Later author decision; not an M1 G0 condition |
