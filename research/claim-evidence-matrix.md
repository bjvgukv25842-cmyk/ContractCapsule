# Claim-Evidence Matrix

Status: M1 analysis protocol frozen before formal experiments and G0
author-approved with bounded scope on 2026-08-02. M2 now supplies engineering
evidence for canonical models, package loading, CAS, and immutable Registry
semantics; M2 human exit approval remains pending. A planned path, unit test,
property test, or product description is not counted as empirical evidence.

## Contribution Claims

| ID | Claim boundary | System artifact | Formal case or experiment | Metric | Paper section | Evidence available through M2 | Evidence still missing | Human validation responsibility |
|---|---|---|---|---|---|---|---|---|
| C1 | A formal source-grounded capsule and behaviorally correct replacement relation, not atoms or compression alone | `docs/protocol/formal-model.md`; `docs/protocol/failure-semantics.md`; `src/contractcapsule/formal.py` | Ten frozen formal cases plus adversarial report-binding, graph-recomputation, duplicate-ID, and unknown-class tests | Well-formedness; evidence resolution; dependency closure; conflict visibility; TER; PIP; BSR; unsafe activation; rollback | Sections 2-4 | Definitions 1-12; 30 executable M1 tests; real Red-Green history | Independent formal review; production proof obligations; empirical replacement behavior | Authors approved the bounded G0 boundary and must review every later benchmark contract |
| C2 | A working CCS-2.1 research prototype that realizes the formal obligations | M2 canonical models and Schema documents; package loader; filesystem CAS; SQLite Registry; later M3-M6 builder, resolver, compiler, validator, swap controller, and adapters | 172 M2 unit/property tests plus M1 formal regressions; later G1 vertical slice | Canonical digest determinism/sensitivity; derived-artifact isolation; load integrity; immutable publication; unauthorized/tampered-read rejection; later closure, traceability, pointer update, rollback | Sections 4-5 | Seven-module strict model; explicit JCS identity; fail-closed package loader; immutable local CAS/Registry; real Red-Green history | M3-M6 production path, behavioral validator, active pointer, adapters, and a real build-to-rollback slice | Authors review M2 field mapping and generic JSON Schema semantic-pass limitation; no M2 mechanism may be reported as the complete prototype |
| C3 | CapsuleBench, an objective benchmark for coding-agent context replacement | M7 task packages, immutable repository locks, gold atoms/spans, target/invariant/spillover tests, adjudication ledger | 24 approved public-repository tasks; old/new setup tests; condition-blind scorers | Task coverage; critical-atom truth; target checks; protected checks; spillover checks; reviewer agreement | Section 6 | Formal case schema and inclusion rules only | Licensed repositories, executable objective truth, author review, 25% independent second review | Human authors validate every target and invariant against source evidence; second reviewer covers at least 25% |
| C4 | Empirical comparison of ContractCapsule with native, full-context, RAG, summary, and atom-only conditions | M7 baselines; M8 pilot; M9 immutable runs; M10 analysis scripts | Paired 24-task Codex study; stratified Claude replication; ablations | RQ1 measures; RQ2 measures; TER/PIP/BSR separately; closure; conflict detection; activation and rollback rates | Sections 6-8 | Conditions, outcomes, exclusions, retry rules, and statistical analysis frozen before formal experiments | No pilot, run, effect size, interval, p-value, or empirical conclusion exists | Authors approve benchmark truth, budget, exclusions, protocol deviations, and interpretation of unfavorable results |
| C5 | Open, auditable, and reproducible research artifacts | Frozen hashes; static Schema set; `uv.lock`; protocol; literature matrix; decision log; AI-use ledger; module reports; later anonymous package | M0-M2 structure/hash/lock/schema/JSONL checks; later M7-M11 replay and clean-environment artifact smoke test | Hash verification; deterministic schema regeneration; environment replay; run coverage; citation audit; anonymity audit; artifact success | Methods; Data Availability; artifact appendix | Baseline locks, Python lock, M0-M2 Red-Green and decision trail, static Schema consistency, verified related-work rows | Anonymous replication package, raw data, analysis replay, citation/anonymity/page audit | Authors remain accountable for M2 exit review, citations, AI disclosure, licenses, anonymity, ethics, data release, and submission |

## Research Questions

| ID | Frozen question | M1 protocol/artifact | Planned evidence and primary outcomes | Current support | Missing result |
|---|---|---|---|---|---|
| RQ1 | Effectiveness and efficiency versus five context baselines | `research/protocol.md`; condition definitions | Primary: repository test pass, contract test pass, task completion, mandatory-constraint adherence, input tokens; secondary: cached tokens, time, reported cost | Measures and paired analysis frozen | No agent task has run; no superiority or non-inferiority claim is supported |
| RQ2 | Explainability and evidence fidelity | Evidence-preservation and view-validity definitions; M2 reciprocal evidence bindings and digest-checked CAS/Git/external records | Primary: critical-atom recall, provenance resolution, source-span correctness, exact expansion; secondary: atom precision/recall, decision completeness, stale detection | Formal traceability plus engineering checks for source-map structure, immutable locators, and local CAS bytes | No real source-map corpus, user audit, or measured provenance/span result exists |
| RQ3 | Replacement correctness and safety | ReplacementCorrect, activation, rollback, and irreversible-effect definitions; M2 immutable publication foundation | TER, PIP, and BSR separately; closure success; conflict detection; unsafe activation; rollback | Formal gates/fail-closed cases and immutable version storage only | No behavioral twin run, activation controller, stochastic distribution, or real task result exists |
| RQ4 | Cross-agent generality and mechanism necessity | Agent-independent interface and pre-specified ablations | Codex primary; Claude replication; A1 closure, A2 contract, A3 source expansion, A4 risk compression | Interface is agent-neutral by definition | No adapter, cross-agent run, ablation, or generality evidence exists |

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

| G0 condition | M1 evidence | Final status after author review |
|---|---|---|
| Replacement correctness has a clear formal definition | `ReplacementCorrect` is a conjunction of valid view, interface, TER/PIP/BSR, evidence, closure, conflict, and irreversible-action controls | Satisfied formally |
| TER, PIP, and BSR are separately measurable | Check-level fractions and aggregate reporting were frozen before formal experiments | Accepted as protocol; no measurements yet |
| Evidence, closure, and conflict are formal conditions | Definitions 2, 4, 5, and 7 plus executable failures | Satisfied formally |
| Activation and rollback are replacement semantics | Definitions 10-12 plus safe-boundary and rollback tests | Satisfied in M1 reference model |
| Ten cases separate safe and unsafe replacement | Exactly ten JSON fixtures assert blocker and active-state outcome | Satisfied executable |
| No core contribution rests only on product description | C1 has formal/test evidence; C2-C5 explicitly retain missing-evidence status | Satisfied for M1 scope |
| Related work is real and verified | Eleven primary-source rows record URLs, retrieval date, basis, and `citation_verified=true` | Satisfied for current matrix; authors must re-audit before submission |

The author approved G0 with bounded scope on 2026-08-02. This does not
imply that C2-C5 or any empirical RQ has been proven. M2 was separately
authorized and its technical evidence remains pending the M2 human exit gate.
Context Codec remains a high-overlap neighbor; atoms, compression,
provenance, RAG, Skill, and MCP are not standalone novelty claims.
