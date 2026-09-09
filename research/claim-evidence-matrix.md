# Claim-Evidence Matrix

M5 proposal status: independent initial review of198616e returned REQUEST
CHANGES; revised2842a13 is READY FOR AUTHOR APPROVAL after four clarifications.
The author approved the exact ADR-0005 text on 2026-09-09; M5-1 is authorized,
but no M5 runtime implementation or behavior result is claimed yet. See
`research/module-reports/M5.md` for the execution boundary.

Latest gate update (recorded2026-09-09): the author approved M4's exit at
technicalbb1d56d/governance1aeeb11 and authorized M5 startup. Original independent
technical PASS and fresh763-test regression remain engineering evidence only.
M5 starts with its separate proposed ADR-0005 review/author approval gate;
validation, behavioral twin runs, active pointer and rollback are not yet
implemented. Earlier pending-M4 language is retained as historical context.

M5 preparation now supplies an isolated approval baseline, fresh763 inherited
regressions, a proposed signed execution/atomic replacement ADR and a bounded
Docker profile feasibility check. None is M5 implementation or a measured
behavioral result. ADR-0005 author approval remains required before semantic
implementation; see `research/module-reports/M5.md`.

Status: M1 analysis protocol frozen before formal experiments and G0
author-approved with bounded scope on 2026-08-02. M2 supplies engineering
evidence for canonical models, package loading, CAS, and immutable Registry
semantics. M3 now supplies bounded engineering evidence for source-grounded
ingestion, source-map binding, quarantine, and an authoritative
approval-gated P0/P1 publication boundary. The original M3 exit candidate was
rejected by a public-path audit; its root-cause remediation and the narrowly
authorized 17-test setup migration were followed by a second failed exit audit.
The five author-confirmed post-audit findings and the later detached-signature
read-binding repair have technical evidence. The 2026-09-05 audit then exposed
a Builder lint-discovery/complexity gap. After separate author authorization,
that issue was repaired without changing ingestion behavior. The new independent
technical exit audit at `2294af3` passes. The author approved the M3 exit at
`4dbf484` on 2026-09-05 and authorized M4 startup, with its ADR gate retained.
The earlier failed report is preserved unchanged, and the repair/reaudit is in
`research/module-reports/M3-2026-09-05-quality-remediation.md`.
The authorized local Schema-parity remediation is technically verified after a
conditional implementation audit, and the author formally approved the M2 exit
gate at `eec2c1fd173748f181dc8b672b3be320035426a8` on 2026-08-03. A planned
path, unit test, property test, or product description is not counted as
empirical evidence.

M4 is now authorized and initialized on `codex/m4-view-compiler` from M3
approval record `9743b34`; ADR-0004's proposal at `7eec393` is author-approved.
The implementation candidate `2ce1653` now provides the real resolver/compiler,
standalone B-zone manifest and locked replay. Clean-archive controller tests:
745 total (all339 original IDs plus406 new),235 frozen M4,30 formal; lint/type/
complexity/lock/build and six targeted mutation checks pass. Three independent
service findings were repaired at `ed7feae`; repair rereview and the integrated
compiler's independent exit audit subsequently completed on2026-09-08 with
REQUEST CHANGES. Git binding/offline repairs pass scoped review; a residual
declaring-owner admission issue and two compiler allocation/privacy issues
require individually approved repairs. This is bounded engineering
evidence, not M4 author approval or any empirical result; see
`research/module-reports/M4.md` and its exact audit handoff.

After the author's explicit R1/R2/R3 repair approval, candidate `bb1d56d`
passes independent integrated technical reaudit on2026-09-08. All three
findings are addressed;763 full tests retain745 prior nodes and add18 repair
regressions. Exact old-method mutations reproduce4/3/6 failures. This advances
M4 to the separate author exit gate, not beyond it. Details and preserved
failure/reaudit evidence: `M4-2026-09-08-remediation.md`. This update supersedes
the open-finding status of old candidates below without rewriting their history.

## Contribution Claims

| ID | Claim boundary | System artifact | Formal case or experiment | Metric | Paper section | Evidence available through M2 | Evidence still missing | Human validation responsibility |
|---|---|---|---|---|---|---|---|---|
| C1 | A formal source-grounded capsule and behaviorally correct replacement relation, not atoms or compression alone | `docs/protocol/formal-model.md`; `docs/protocol/failure-semantics.md`; `src/contractcapsule/formal.py` | Ten frozen formal cases plus adversarial report-binding, graph-recomputation, duplicate-ID, and unknown-class tests | Well-formedness; evidence resolution; dependency closure; conflict visibility; TER; PIP; BSR; unsafe activation; rollback | Sections 2-4 | Definitions 1-12; 30 executable M1 tests; real Red-Green history | Independent formal review; production proof obligations; empirical replacement behavior | Authors approved the bounded G0 boundary and must review every later benchmark contract |
| C2 | A working CCS-2.1 research prototype that realizes the formal obligations | M2 canonical models and Schema documents; package loader; filesystem CAS; SQLite Registry; M3 source-grounded builder, quarantine, and final Registry trust gate; later M4-M6 resolver, compiler, validator, swap controller, and adapters | 219 current M2-path unit/property tests, 72 current M3 integration/security tests and 13 M3 scan/ingestion regressions, plus M1 formal regressions; later G1 vertical slice | Canonical digest determinism/sensitivity; derived-artifact isolation; load integrity; immutable publication; source-map fidelity; trust-promotion and final-publication fail-closed behavior; unauthorized/tampered-read rejection; local Schema/Python assertion parity; later closure, traceability, pointer update, rollback | Sections 4-5 | Seven-module strict model; explicit JCS identity; fail-closed package loader; immutable local CAS/Registry; local Schema parity; deterministic source snapshots and structural atomization; Git/CAS/external evidence bindings; trusted-collector boundary; transaction-time exact Git-object/loader/CAS/Evidence/approval revalidation; attestation rollback/replay and persisted-signature read-binding evidence; real behavior-level Red-Green and mutation history | M4-M6 production path, behavioral validator, active pointer, adapters, and a real build-to-rollback slice | Authors approved the M2 field mapping, remediation, and disclosed generic JSON Schema semantic-pass boundary at `eec2c1f`; M3 remediation remains engineering-only; the independent quality reaudit at 2294af3 passes all technical gates, and the author approved M3 at 4dbf484 on 2026-09-05 |
| C3 | CapsuleBench, an objective benchmark for coding-agent context replacement | M7 task packages, immutable repository locks, gold atoms/spans, target/invariant/spillover tests, adjudication ledger | 24 approved public-repository tasks; old/new setup tests; condition-blind scorers | Task coverage; critical-atom truth; target checks; protected checks; spillover checks; reviewer agreement | Section 6 | Formal case schema and inclusion rules only | Licensed repositories, executable objective truth, author review, 25% independent second review | Human authors validate every target and invariant against source evidence; second reviewer covers at least 25% |
| C4 | Empirical comparison of ContractCapsule with native, full-context, RAG, summary, and atom-only conditions | M7 baselines; M8 pilot; M9 immutable runs; M10 analysis scripts | Paired 24-task Codex study; stratified Claude replication; ablations | RQ1 measures; RQ2 measures; TER/PIP/BSR separately; closure; conflict detection; activation and rollback rates | Sections 6-8 | Conditions, outcomes, exclusions, retry rules, and statistical analysis frozen before formal experiments | No pilot, run, effect size, interval, p-value, or empirical conclusion exists | Authors approve benchmark truth, budget, exclusions, protocol deviations, and interpretation of unfavorable results |
| C5 | Open, auditable, and reproducible research artifacts | Frozen hashes; static Schema set; `uv.lock`; protocol; literature matrix; decision log; AI-use ledger; module reports; later anonymous package | M0-M3 structure/hash/lock/schema/JSONL checks; later M7-M11 replay and clean-environment artifact smoke test | Hash verification; deterministic schema regeneration; environment replay; source/test provenance; run coverage; citation audit; anonymity audit; artifact success | Methods; Data Availability; artifact appendix | Baseline locks, Python lock, M0-M3 Red-Green and decision trail, static Schema consistency, verified related-work rows, M3 source-map/security test record | Anonymous replication package, raw data, analysis replay, citation/anonymity/page audit | Authors approved the M2 exit record; M3 human exit approved at 4dbf484; authors remain accountable for citations, AI disclosure, licenses, anonymity, ethics, data release, and submission |

## Research Questions

| ID | Frozen question | M1 protocol/artifact | Planned evidence and primary outcomes | Current support | Missing result |
|---|---|---|---|---|---|
| RQ1 | Effectiveness and efficiency versus five context baselines | `research/protocol.md`; condition definitions | Primary: repository test pass, contract test pass, task completion, mandatory-constraint adherence, input tokens; secondary: cached tokens, time, reported cost | Measures and paired analysis frozen | No agent task has run; no superiority or non-inferiority claim is supported |
| RQ2 | Explainability and evidence fidelity | Evidence-preservation and view-validity definitions; M2 reciprocal evidence bindings and digest-checked CAS/Git/external records; M3 deterministic snapshots and source-map quarantine | Primary: critical-atom recall, provenance resolution, source-span correctness, exact expansion; secondary: atom precision/recall, decision completeness, stale detection | Formal traceability plus M2 integrity checks and M3 engineering checks for deterministic source maps, immutable locators, approval coverage, secret gates, and local CAS bytes | No real source-map corpus, user audit, or measured provenance/span result exists |
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

The author approved G0 with bounded scope on 2026-08-02. This does not imply
that C2-C5 or any empirical RQ has been proven. The author separately accepted
the M2 remediation and formally approved the M2 exit gate on 2026-08-03; that
decision accepts engineering evidence only and adds no empirical result. M3
implementation evidence is likewise limited to source fidelity and trust
promotion; its human exit gate was approved at `4dbf484` on 2026-09-05.
Context Codec remains a high-overlap neighbor; atoms, compression, provenance,
RAG, Skill, and MCP are not standalone novelty claims. M4 startup is authorized;
the collective-interface ADR is accepted, while the M4 exit still requires an
independent technical audit and author approval.

## M4 Engineering Evidence Pointer

The latest M4 report and `M4-verification/` retain exact commands, failures,
source identity and scope. These additions supplement the historical M2/M3
columns above; they do not turn protocol or implementation tests into empirical
support for the contribution claims.

| Claim/question | New engineering support | Still missing |
|---|---|---|
| C2 | Genuine Registry-to-compiled-view path; permission isolation, deterministic FTS5, two-level closure, locked release providers, P0/P1 budget failure, native evidence and replay | Independent M4 exit audit and author approval; M5-M6 validator/swap/adapters and G1 slice |
| RQ1 | Offline versioned real token counts for complete rendered text; component counts and nonadditive boundary adjustment | Agent-task comparison, runtime cost/efficiency or superiority results |
| RQ2 | Every admitted atom's selection/exclusion, exact source handles and expansion checks; fixture-level mandatory P0 retention | Human-verified corpus, empirical critical-atom recall and provenance/span measurements |
| C5 | Exact candidate archive, original339 retention, protected baseline hashes, packaged tokenizer checks and falsification logs | Independent exit review, anonymous artifact and external replication |

The original service audit returned REQUEST CHANGES, not PASS. Local repairs
and passing tests do not rewrite that verdict. All M4 material remains an
author-unapproved exit candidate; no M5 or formal experiment has started.

### Independent Exit Audit Update (2026-09-08)

Two independent reviewers completed the scoped service rereview and full exit
audit at technical2ce1653/governancecd6cfcf. Independent235/745/30 regression
checks,10 targeted mutations, type/lint/complexity/lock/schema/build and governance
checks are now available. They do not close M4: M4-R1 graph owner admission,
M4-R2 replaceable-ranker allocation precedence and M4-R3 late-revocation metadata
privacy require fixes. Original Git locator and offline-read findings have
scoped PASS, not whole-system PASS. Additional diagnostics are counted separately
from745 existing nodes and are not empirical results. Exact reports and minimal
repair scopes are in `M4-2026-09-08-independent-exit-audit.md`.

### Approved Repair Reaudit Update (2026-09-08)

Exactbb1d56d now has independent technical PASS after the author-approved
R1/R2/R3 repairs. C2 gains verified source-owner admission, fixed allocation
and safe invalidated failure projections; RQ1/RQ2 gain corrected engineering
instrumentation, not empirical results. Public token zeros accompanying
AUTHORIZATION_SNAPSHOT_INVALIDATED represent redacted detail, not free work;
those entries must not be treated as actual zero-cost research observations.
All previous tests/core schemas/protocol/dependency identities remain, with
runtime graph1.0.1 and compiler0.1.2 stamps distinguishing corrected replay.
Author M4 exit, M5-M6 vertical slice, human benchmark truth and formal empirical
results remain outstanding.

## M3 Engineering Evidence Pointer

`research/module-reports/M3.md` records the source-ingestion, deterministic
atomization, evidence-binding, quarantine, approval, secret-scanning, and
Registry-enforced public build/load/publish evidence. The original 28-test M3
record and previous failed exit audits are preserved. The candidate at `2294af3`
retains all 326 prior nodes and adds 13 scan/ingestion regressions, for 339
committed tests. Its new independent audit verifies full 36/36 Python-file
discovery, unchanged complexity thresholds, original-production characterization,
and source/test preservation. Deliberate scan omission, late validation/CAS
persistence and Registry projection bypass each make their regression fail;
restoring the code makes all gates pass. The 17 supplemental security diagnostics
are reported separately, not added to the committed-suite count. The previous
incomplete-scan success remains qualified as historical evidence; this new
complete audit closes the finding at the new commit. These are engineering
tests, not benchmark observations or empirical TER/PIP/BSR, C2-C5, baseline
advantage or cross-agent results. M3's technical reaudit and human exit gate
are approved; M4 is authorized to start after this governance record, with no
M4 implementation result claimed here.
