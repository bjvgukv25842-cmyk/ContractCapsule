# Claim-Evidence Matrix

Status: M1 protocol candidate, 2026-08-01. M0 is closed. G0 remains subject to
human author approval. A planned path, test, or product description is not
counted as empirical evidence.

## Contribution Claims

| ID | Claim boundary | System artifact | Formal case or experiment | Metric | Paper section | Evidence available at M1 | Evidence still missing | Human validation responsibility |
|---|---|---|---|---|---|---|---|---|
| C1 | A formal source-grounded capsule and behaviorally correct replacement relation, not atoms or compression alone | `docs/protocol/formal-model.md`; `docs/protocol/failure-semantics.md`; `src/contractcapsule/formal.py` | Ten frozen formal cases plus adversarial report-binding, graph-recomputation, duplicate-ID, and unknown-class tests | Well-formedness; evidence resolution; dependency closure; conflict visibility; TER; PIP; BSR; unsafe activation; rollback | Sections 2-4 | Definitions 1-12; 30 executable M1 tests; real Red-Green history | Independent formal review; production proof obligations; empirical replacement behavior | Authors verify definitions match CCS-2.1, approve G0 boundary, and review every later benchmark contract |
| C2 | A working CCS-2.1 research prototype that realizes the formal obligations | M2-M6 builder, immutable storage, resolver, compiler, validator, swap controller, and two adapters | M2-M6 unit/property/integration/security tests and G1 vertical slice | Integrity pass; deterministic view rebuild; closure; traceability; atomic pointer update; rollback success | Sections 4-5 | M1 executable reference semantics only | All production components and a real build-to-rollback slice | Authors verify no M1 reference model is misreported as the finished system |
| C3 | CapsuleBench, an objective benchmark for coding-agent context replacement | M7 task packages, immutable repository locks, gold atoms/spans, target/invariant/spillover tests, adjudication ledger | 24 approved public-repository tasks; old/new setup tests; condition-blind scorers | Task coverage; critical-atom truth; target checks; protected checks; spillover checks; reviewer agreement | Section 6 | Formal case schema and inclusion rules only | Licensed repositories, executable objective truth, author review, 25% independent second review | Human authors validate every target and invariant against source evidence; second reviewer covers at least 25% |
| C4 | Empirical comparison of ContractCapsule with native, full-context, RAG, summary, and atom-only conditions | M7 baselines; M8 pilot; M9 immutable runs; M10 analysis scripts | Paired 24-task Codex study; stratified Claude replication; ablations | RQ1 measures; RQ2 measures; TER/PIP/BSR separately; closure; conflict detection; activation and rollback rates | Sections 6-8 | Conditions, outcomes, exclusions, retry rules, and statistical analysis preregistered | No pilot, run, effect size, interval, p-value, or empirical conclusion exists | Authors approve benchmark truth, budget, exclusions, protocol deviations, and interpretation of unfavorable results |
| C5 | Open, auditable, and reproducible research artifacts | Frozen hashes; `uv.lock`; protocol; literature matrix; decision log; AI-use ledger; module reports; later anonymous package | M0/M1 checks now; M7-M11 replay and clean-environment artifact smoke test | Hash verification; environment replay; run coverage; citation audit; anonymity audit; artifact success | Methods; Data Availability; artifact appendix | Baseline locks, Python lock, M0/M1 audit trail, verified related-work rows | Anonymous replication package, raw data, analysis replay, citation/anonymity/page audit | Authors remain accountable for citations, AI disclosure, licenses, anonymity, ethics, data release, and submission |

## Research Questions

| ID | Frozen question | M1 protocol/artifact | Planned evidence and primary outcomes | Current support | Missing result |
|---|---|---|---|---|---|
| RQ1 | Effectiveness and efficiency versus five context baselines | `research/protocol.md`; condition definitions | Primary: repository test pass, contract test pass, task completion, mandatory-constraint adherence, input tokens; secondary: cached tokens, time, reported cost | Measures and paired analysis frozen | No agent task has run; no superiority or non-inferiority claim is supported |
| RQ2 | Explainability and evidence fidelity | Evidence-preservation and view-validity definitions; valid, missing-evidence, stale-evidence, and stripped-view tests | Primary: critical-atom recall, provenance resolution, source-span correctness, exact expansion; secondary: atom precision/recall, decision completeness, stale detection | Formal traceability can be falsified in M1 | No real source-map, user audit, or measured provenance result exists |
| RQ3 | Replacement correctness and safety | ReplacementCorrect, activation, rollback, and irreversible-effect definitions; ten formal cases | TER, PIP, and BSR separately; closure success; conflict detection; unsafe activation; rollback | Strongest M1 support: formal gates and fail-closed cases | No stochastic twin run, behavioral distribution, or real task result exists |
| RQ4 | Cross-agent generality and mechanism necessity | Agent-independent interface and preregistered ablations | Codex primary; Claude replication; A1 closure, A2 contract, A3 source expansion, A4 risk compression | Interface is agent-neutral by definition | No adapter, cross-agent run, ablation, or generality evidence exists |

## Related-Work Boundary

The verified row-level evidence is in `research/literature.csv`.

| Neighbor | What it establishes | What it does not establish | ContractCapsule claim boundary |
|---|---|---|---|
| Summary plus metadata | A compact description can carry labels or fields | Mandatory closure, immutable per-atom evidence, behavioral old/new contract, atomic activation, rollback | Seven-module immutable unit plus validated replacement relation |
| Compression-only | Prompt length/cost can fall while utility is measured | Which behavior must change, which must not, forbidden spillover, prior-version recovery | Compression is a policy inside a replacement protocol |
| Retrieval-only/RAG | Relevant passages can augment generation | Closure after Top-k, conflict gate, exact P0, replacement correctness | Eligibility, closure, validation, and activation surround retrieval |
| Memory-only | Context can persist or move across tiers | Published-core immutability and behaviorally checked version substitution | Memory is storage/reuse; ContractCapsule is a contract-bearing replacement unit |
| Atom-only | Typed source-grounded commitments can make compression auditable | Old/new interface compatibility, TER/PIP/BSR, task/report binding, atomic activation, rollback | Atoms are one module; novelty is the verifiable replacement composition |

MCP, Skills, provenance formats, package manifests, schemas, embeddings, and
cache tiers are integration or implementation mechanisms. None is claimed as
an independent contribution.

## G0 Evidence Audit

| G0 condition | M1 evidence | Status before author review |
|---|---|---|
| Replacement correctness has a clear formal definition | `ReplacementCorrect` is a conjunction of valid view, interface, TER/PIP/BSR, evidence, closure, conflict, and irreversible-action controls | Satisfied formally |
| TER, PIP, and BSR are separately measurable | Check-level fractions and aggregate reporting are preregistered | Satisfied as protocol; no measurements yet |
| Evidence, closure, and conflict are formal conditions | Definitions 2, 4, 5, and 7 plus executable failures | Satisfied formally |
| Activation and rollback are replacement semantics | Definitions 10-12 plus safe-boundary and rollback tests | Satisfied in M1 reference model |
| Ten cases separate safe and unsafe replacement | Exactly ten JSON fixtures assert blocker and active-state outcome | Satisfied executable |
| No core contribution rests only on product description | C1 has formal/test evidence; C2-C5 explicitly retain missing-evidence status | Satisfied for M1 scope |
| Related work is real and verified | Eleven primary-source rows record URLs, retrieval date, basis, and `citation_verified=true` | Satisfied for current matrix; authors must re-audit before submission |

M1 supports a recommendation to pass G0, subject to author review. It does not
authorize M2 and does not imply that C2-C5 or any empirical RQ has been proven.
