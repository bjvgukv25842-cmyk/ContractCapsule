# Decision Log

## M0-001 - Frozen inputs accepted

- Date: 2026-08-01
- Status: accepted for M0
- Decision: retain the root-level source files and copy them byte-for-byte to
  their normative `docs/` paths.
- Evidence: source and target files pass `cmp`; both SHA-256 values match the
  frozen values.

## M0-002 - Existing repository root retained

- Date: 2026-08-01
- Status: accepted
- Decision: `/Users/litmus/Documents/Contract Capsule` is the repository root.
  No nested `contract-capsule/` directory and no new Git repository are created.
- Existing user files are preserved. `.DS_Store` is ignored and is not a
  project input.

## M0-003 - Manual execution-driver waiver

- Date: 2026-08-01
- Status: author-approved for M0 only
- Decision: execute the frozen M0 checklist manually because
  `superpowers:executing-plans` is not registered as an available Skill in this
  session.
- Boundary: this does not waive the frozen design, module order, TDD, tests,
  research integrity, AI-use records, invariants, or human exit gate. The Skill
  was not installed, loaded, or claimed as used.

## M0-004 - Python project initialization

- Date: 2026-08-01
- Status: accepted
- Decision: initialize the existing repository with
  `uv init --python 3.12 --lib --name contractcapsule --vcs none --author-from none .`.
- Rationale: `--vcs none` preserves the existing Git repository,
  `--author-from none` avoids inventing author metadata, and the explicit name
  matches the frozen `src/contractcapsule/` package path.
- Environment: uv 0.12.1, CPython 3.12.13.

## M0-005 - Baseline lock behavior

- Date: 2026-08-01
- Status: implemented and tested
- Decision: lock both frozen baselines by target path and approved SHA-256.
  Missing files and digest mismatches raise `FrozenBaselineMismatch`.
- TDD evidence: the first test run failed during collection because
  `contractcapsule.spec_lock` did not exist; the minimal implementation then
  made all four tests pass.

## M0-006 - AI metadata limitation

- Date: 2026-08-01
- Status: open risk
- Decision: record unavailable model ID, original prompt digest, and preexisting
  commit as unavailable rather than fabricate values. The repository had an
  unborn branch before M0.
- Follow-up: later experiment harnesses must capture machine-readable agent and
  prompt metadata as required by the frozen plan.

## M0-007 - Human gate status

- Date: 2026-08-01
- Confirmed: FSE 2027 Research Papers target; CCS-2.1 digest.
- Pending: final authors and affiliations; conflicts of interest; ethics or
  human-participant review; repository license and citation metadata.
- Consequence: M1 cannot start until the author approves the M0 exit gate.

## M0-008 - Local commit blocked by missing Git identity

- Date: 2026-08-01
- Status: resolved on 2026-08-01
- Evidence: the guarded identity check exited 1; both `user.name` and
  `user.email` are missing.
- Decision: do not infer or write an identity, do not stage or commit files, and
  do not push.
- Resolution: after the author requested configuration, the repository owner
  was verified through GitHub's public user API. Repository-local Git identity
  now uses the public profile name and GitHub-generated noreply address. Global
  Git configuration was not changed.
- Boundary: Git commit identity does not confirm the paper author list or
  affiliations; those remain pending at the human gate.

## M0-009 - GitHub remote connected

- Date: 2026-08-01
- Status: configured
- Decision: set `origin` to
  `https://github.com/bjvgukv25842-cmyk/ContractCapsule.git`.
- Verification: `git ls-remote ... HEAD` exited 0 without returning a HEAD,
  consistent with an empty remote repository; local fetch and push URLs both
  resolve to the approved HTTPS URL.
- Boundary: no upstream branch was set and no commit or push was performed.

## M0-010 - Repository-local Git identity configured

- Date: 2026-08-01
- Status: configured
- Evidence source: GitHub public API for `bjvgukv25842-cmyk` returned public
  profile name `LITMUS`, numeric ID `243147736`, and no public email.
- Decision: configure repository-local `user.name` from the public profile and
  use GitHub's ID-plus-login noreply address for commit attribution and privacy.
- Boundary: no private email was inferred, global configuration was unchanged,
  and this identity is not treated as a confirmed paper author identity.

## M0-011 - M0 technical commit created

- Date: 2026-08-01
- Status: completed
- Commit: `52a5c2da76143a53eb8a554b6550eee5d9dfffcf`.
- Message: `chore: bootstrap ContractCapsule FSE research project`.
- Verification: commit exited 0 and contains the 20 reviewed M0 files.
- Boundary: no upstream was set and no push was performed.

## M0-012 - Human exit gate approved

- Date: 2026-08-01
- Status: approved; M0 closed
- Decision: the author approved the FSE 2027 Research Papers target, both
  frozen baseline digests, the M0 technical and audit outputs, the final
  author/affiliation gate, the submission-conflict gate, and the current
  ethics-scope gate.
- Privacy boundary: tracked public research files record approval status only.
  Names, affiliations, email addresses, contribution details, and any future
  detailed conflict disclosures remain outside tracked public files.
- Conflict status: the author reports no known submission conflicts.
- Ethics scope: the current protocol evaluates coding agents and publicly
  licensed repositories without collecting human-participant data. Author or
  collaborator validation of task labels is not research-subject data.
- Reopen condition: user studies, interviews, surveys, private developer data,
  crowdsourced labeling, or identifiable telemetry reopen the ethics gate and
  require review under the authors' institutional rules.
- Verification: both frozen sources and normative copies remain byte-identical
  with approved digests; the 4-test cumulative suite, Ruff, and uv lock checks
  all exit 0; the tracked-file identity scan finds no supplied author details.
- Boundary: approval closes M0 but does not waive M1's required execution
  Skill, isolated workspace, TDD, G0, or any later human gate.

## M0-013 - M1 execution preflight blocked

- Date: 2026-08-01
- Status: resolved on 2026-08-01 in the later M1 session
- Evidence: `superpowers:executing-plans` is absent from the current session's
  registered Available Skills inventory.
- Decision: cached or discoverable files are not treated as a registered Skill,
  and the M0 manual-execution waiver is not extended to M1.
- Historical consequence: no M1 branch, worktree, formal model, fixture,
  literature entry, or implementation was created while the Skill was absent.
- Resolution: a later session registered the official curated Superpowers
  plugin and exposed `superpowers:executing-plans` as an available Skill. Its
  complete `SKILL.md` and required worktree, TDD, subagent, review, and branch
  workflow instructions were read before M1 work began. No manual M0 waiver
  was reused and no unknown code was installed.

## M1-001 - M1 authorization and schedule

- Date: 2026-08-01
- Status: accepted for M1 only
- Decision: execute M1, and no other module, under the author's explicit
  authorization after M0 closure.
- Schedule: M1's frozen window is 2026-08-03 through 2026-08-07. Work began two
  days early rather than late. The author explicitly authorized M1; no module,
  integrity, test, or human gate was skipped.
- Boundary: M2-M11, production CAS/Registry/Builder/Resolver, adapters, MCP,
  Skill, benchmark experiments, and UI remain unauthorized.

## M1-002 - Isolated worktree and branch

- Date: 2026-08-01
- Status: implemented
- Decision: use branch `codex/m1-formal-model` in isolated worktree
  `.worktrees/m1-formal-model`, based on `78d913f` after adding the worktree
  directory to `.gitignore` on the M0 branch.
- Verification: the M1 baseline had 4 passing tests, Ruff passed, Python was
  3.12.13, and both frozen hashes matched before implementation.
- Boundary: no push or merge is performed at M1.

## M1-003 - Executable reference semantics and TDD

- Date: 2026-08-01
- Status: implemented; G0 author review pending
- Decision: implement a pure in-memory M1 reference model in
  `src/contractcapsule/formal.py`; keep schemas, persistence, and durable active
  pointers in their later frozen modules.
- Initial Red: formal-case collection exited 2 with
  `ModuleNotFoundError: contractcapsule.formal`.
- Initial Green: 18 formal tests and 22 cumulative tests passed; Ruff and mypy
  passed.
- Review Red: independent specification review reproduced fail-open report
  substitution, metadata stripping, duplicate identity, and unknown
  compression-class defects. Added regressions produced 12 failures, with the
  original active reference demonstrably changing in the exploitable paths.
- Review Green: report/candidate/task fingerprints, recomputed view invariants,
  identifier checks, exact blocker assertions, and interface-before-ranking
  made 30 formal tests pass. The historical failures remain recorded; they
  were not hidden or weakened.

## M1-004 - Replacement and rollback boundary

- Date: 2026-08-01
- Status: accepted as the M1 model boundary
- Decision: activation receipts model the all-or-nothing active-reference
  transition and retain the prior reference. The in-memory fingerprints bind a
  single decision but do not substitute for M2 integrity storage or M5 durable
  pointer transactions.
- Irreversible effects: rollback restores future context only. An external
  action requires preflight, approval, or compensation and is never described
  as transactionally undone by context rollback.

## M1-005 - Related-work verification

- Date: 2026-08-01
- Status: completed for the M1 matrix; submission re-audit still required
- Decision: record only claims checked against primary papers, publisher pages,
  arXiv primary manuscripts, or official technical/product documentation.
- Evidence: `research/literature.csv` contains eleven rows with authors,
  venue/specification, DOI where available, direct URL, retrieval date,
  verification basis, boundary class, overlap risk, and citation status.
- Closest overlap: Context Codec is high risk because it already formalizes
  typed source-grounded atoms and verifiable commitment preservation. The M1
  claim therefore excludes atoms and compression and rests on behavioral
  old/new replacement, TER/PIP/BSR, task/report binding, atomic activation, and
  rollback.
- Boundary: a verified citation means its recorded metadata and matrix claim
  were checked; it is not a judgment that every source is peer reviewed. arXiv
  works and official documentation are labeled as such.

## M1-006 - Analysis protocol frozen before formal experiments

- Date: 2026-08-01
- Status: frozen candidate pending G0 author approval
- Decision: freeze RQ1-RQ4, primary and secondary outcomes, conditions,
  ablations, units of analysis, inclusion/exclusion rules, infrastructure-only
  retry policy, and statistical test families in `research/protocol.md` before
  any full experiment.
- Statistics: task-level paired aggregation, task-cluster bootstrap intervals,
  exact McNemar for paired binary outcomes, paired permutation tests for
  numeric/rate outcomes, pre-specified Wilcoxon sensitivity conditions, effect
  sizes, and Holm correction within RQ families.
- Boundary: M8 may freeze draw counts after runtime preflight but cannot select
  tests or outcomes from favorable directions. Protocol amendments are
  versioned and preserve prior text.

## M1-007 - G0 novelty assessment

- Date: 2026-08-01
- Status: recommend pass; human author decision pending
- Decision: M1 artifacts distinguish ContractCapsule from summary plus
  metadata, compression-only, retrieval-only, memory-only, and atom-only work.
- Basis: replacement correctness is explicitly defined; TER/PIP/BSR are
  separately measurable; evidence, closure, conflict, activation, rollback,
  and irreversible effects are formal conditions; exactly ten frozen cases
  separate safe and unsafe state transitions; core contributions do not rely
  only on a product description; related-work rows are source-verified.
- Limitation: this is formal and protocol evidence, not a claim that C2-C5 or
  any empirical RQ already succeeds. M2 remains blocked until author approval.

## M1-008 - Restricted G0 author approval

- Date: 2026-08-02
- Status: APPROVED TO PROCEED
- Decision: the author approved the G0 novelty stop gate on the strength of the
  formal replacement definition, separately measurable TER/PIP/BSR,
  evidence preservation, mandatory dependency closure, conflict visibility,
  interface compatibility, atomic activation, safe rollback, and the ten
  executable formal cases.
- Approved claim boundary: “面向 Coding Agent 的、带不可变证据与依赖闭包、由行为契约验证、支持原子激活和安全回滚的版本化项目上下文替换机制。”
- Explicit non-results: this decision does not establish C2-C5, observed
  TER/PIP/BSR, superiority over a baseline, cross-agent generality, or removal
  of the Context Codec overlap risk.
- Novelty exclusions: typed atoms, canonical identity, conflicts, evidence
  spans, provenance, compression verification, RAG, Skill, and MCP are not
  standalone contributions.
- Related-work risk: Context Codec remains the highest-overlap neighboring
  work and must remain marked high risk.
- Registration boundary: `research/protocol.md` is an analysis protocol frozen
  before formal experiments. Local Git history is not described as a public
  external preregistration because no independent timestamped registration
  platform has been recorded.
- Privacy boundary: tracked files record the decision status and scope only;
  no author identity, email, or detailed conflict information is added.
- Integration: the author selected Option 1, local merge into the uniquely
  verified baseline branch after all required checks pass. No pull, push, PR,
  or M2 work is authorized by this decision.

## M2-001 - Early-start authorization and pre-implementation stop

- Date: 2026-08-02
- Status: author-approved schedule deviation; resolved safety stop
- Decision: begin M2 six days before its frozen 2026-08-08 through 2026-08-12
  window from the verified M1 integration commit
  `c24696e88117b70ed386d586ce9d548951f6287d`.
- Boundary: the early start does not waive module order, TDD, frozen hashes,
  fail-closed behavior, research integrity, verification, or the M2 human exit
  gate. M3-M11 remain unauthorized.
- Stop history: the first M2 preflight stopped before branch creation or file
  modification because canonical self-reference, CAS authorization, identical
  republish behavior, and evidence storage modes were not uniquely specified.
  The author reviewed that report and supplied the implementation decisions
  recorded below. No code or research artifact was changed before approval.

## M2-002 - CCS-2.1-canonical-v1 implementation configuration

- Date: 2026-08-02
- Status: author-approved for M2 implementation
- Canonical identity: construct an explicit seven-module A-zone projection
  named `CCS-2.1-canonical-v1`; encode it with RFC 8785/JCS-compatible JSON and
  return `sha256:` followed by 64 lowercase hexadecimal characters.
- Included identity content: all declared semantic and security fields of the
  Control Manifest, Semantic Payload, Evidence Plane, Dependency Graph,
  Replacement Contract, Compression Policy, and Tests & Integrity, including
  authority, scope, lifecycle, evidence digests, access policies, dependency
  edges, tests, locks, and permitted core extensions.
- Excluded identity content: `manifest.content_digest`, repeated root-digest
  copies, detached signature values and transport envelopes, any package-byte
  digest, and all B-zone or C-zone derivatives including embeddings, caches,
  compiled views, indexes, runtime logs, observations, and runtime timestamps.
  M2 does not add a public package-digest field or signature implementation.
- Canonical input rules: reject duplicate JSON keys, invalid UTF-8, lone
  surrogates, NaN, infinities, coercive or ambiguous numeric inputs, and
  undeclared fields outside the permitted extension namespace. Do not perform
  Unicode normalization. Preserve array order unless a specific schema field
  is explicitly modeled as a set with a unique ordering key.
- Signature boundary: a later signer will sign
  `b"CCS-2.1-signature-v1\\0" + content_digest.encode("ascii")`; M2 neither
  implements nor claims production signature security. M1 `repr()`-based
  fingerprints remain decision witnesses only.
- CAS authorization: one repository/authority trust domain; blob writes grant
  no read permission. A test-injectable trusted Policy Resolver defaults to
  deny. Capsule authority/scope/access-policy declarations may only narrow the
  Resolver decision. Successful publication atomically stores the immutable
  publication, evidence references, and digest grants. Public reads require at
  least one authorized published reference and reverify stored bytes.
- Grant composition: distinct valid published references to identical bytes
  form a read-permission union, while each reference is independently checked
  by the trusted Resolver. Cross-tenant isolation, revocation, dynamic roles,
  and distributed authorization are outside M2.
- Republish rule: an exact immutable publication is idempotent only after
  caller authorization and full stored-field equality checks; it performs no
  write, timestamp update, new grant, or duplicate evidence insertion. The
  same ID/version with a different digest or immutable metadata fails closed.
  The Registry uses a unique `(capsule_id, version)` key and never uses replace
  semantics.
- Evidence modes: `CAS` requires a locally present, digest-verified blob;
  `GIT_IMMUTABLE` requires a normalized repository identity, algorithm-tagged
  full commit OID, literal safe repository-relative path, evidence digest, and
  media type; `EXTERNAL_IMMUTABLE` requires a normalized HTTPS or permitted
  persistent URI, digest, media type, and source-verification metadata. Modes
  never silently fall back and M2 performs no network retrieval.
- Protocol boundary: this is an M2 implementation configuration and does not
  modify CCS-2.1, the frozen execution plan, or the frozen analysis protocol.

## M2-003 - Explicit canonical identity field projection

- Date: 2026-08-02
- Status: implemented and executable; M2 human exit pending
- Root domain field: `profile`, fixed to `CCS-2.1-canonical-v1`.
- Included Control Manifest paths:
  `core.control_manifest.spec_version`, `.canonical_profile`, `.capsule_id`,
  `.version`, `.owner`, `.tenant`, `.scope.repositories[]`, `.scope.paths[]`,
  `.scope.environments[]`, `.authority`, `.sensitivity`, `.provides[]`,
  `.requires[]`, `.conflicts[]`, `.lifecycle`, `.created_from[]`,
  `.integrity.lock`, `.integrity.signature`, and `.extensions.*`.
- Included Semantic Payload paths: `core.semantic_payload.extensions.*` and,
  for every ordered `atoms[]` entry, `.atom_id`, `.kind`, `.statement`,
  `.modality`, `.scope[]`, `.exceptions[]`, `.validity.from`,
  `.validity.until`, `.authority`, `.status`, `.confidence`,
  `.evidence_refs[]`, `.requires_atoms[]`, `.conflicts_with[]`,
  `.sensitivity`, `.compression_class`, `.refresh_policy`, and
  `.extensions.*`.
- Included Evidence Plane paths: `core.evidence_plane.extensions.*` and, for
  every ordered `records[]` entry, `.mode`, `.evidence_id`, `.atom_ids[]`,
  `.content_digest`, `.media_type`, `.captured_at`, `.retention`,
  `.access_policy`, `.validation`, and `.extensions.*`. A
  `GIT_IMMUTABLE` record additionally includes `.repository`, `.revision`,
  `.path`, `.locator.symbol_or_heading`, `.locator.start_line`,
  `.locator.end_line`, and `.locator.span_digest`; an
  `EXTERNAL_IMMUTABLE` record additionally includes `.uri`, `.source`, and
  `.verification_method`.
- Included Dependency Graph paths: `core.dependency_graph.extensions.*` and,
  for every ordered `edges[]` entry, `.source`, `.target`, `.edge_type`,
  `.version_constraint`, `.mandatory`, and `.extensions.*`.
- Included Replacement Contract paths:
  `core.replacement_contract.contract_id`, `.replaces`, `.preconditions[]`,
  `.target_effects[]`, `.protected_invariants[]`, `.allowed_scope[]`,
  `.forbidden_spillover[]`, `.verification.static[]`,
  `.verification.behavioral[]`, `.verification.differential[]`,
  `.activation.risk`, `.activation.approval_required`,
  `.activation.safe_boundary`, `.rollback.pointer`,
  `.rollback.compensating_action`, and `.extensions.*`.
- Included Compression Policy paths: `core.compression_policy.policy_version`,
  `.extensions.*`, and for every ordered `.classes[]` entry, `.name`,
  `.rendering`, `.lossy_compression`, `.expansion_triggers[]`, and `.ttl`.
- Included Tests & Integrity paths: `core.tests_integrity.extensions.*`; for
  every ordered `.tests[]` entry, `.test_id`, `.kind`, `.path`, and `.digest`;
  `.lock.capsule_dependencies[].capsule_id`, `.version`, and `.digest`;
  `.lock.source_commits[]`, `.compiler_version`, `.adapter_versions[]`,
  `.compression_policy_version`, `.test_set_version`, `.model_series[]`,
  `.parameters[]`, `.runtime_config_digest`, and `.extensions.*`; every
  `.artifact_checksums[].path` and `.digest`; and
  `.signature_policy.algorithm`, `.key_id`, and `.input_profile`.
- Explicit exclusions: `core.control_manifest.content_digest`; any repeated
  root-digest carrier; `detached_signature.algorithm`, `.key_id`, `.value`,
  and `.envelope.*` as a transport record (the normative algorithm/key/profile
  are bound through `tests_integrity.signature_policy`); any package-byte
  digest; `derived_artifacts.*`; and `runtime_sidecar.*`.
- Ordering: all arrays retain input order and order is identity-relevant under
  the author's canonical-v1 decision. M1's set notation defines semantic
  membership; it is not reused as the production byte-order rule. No field has
  an author-approved unique sorting key in CCS-2.1-canonical-v1.
- Encoding: the projection alone is encoded with RFC 8785/JCS as UTF-8. There
  is no Unicode normalization, no insignificant whitespace, no implicit type
  conversion, and no serialization of the full Capsule followed by a
  blacklist.

## M2-004 - Schema and package trust boundary

- Date: 2026-08-02
- Status: implemented; generic-validator limitation disclosed
- Decision: publish eight Draft 2020-12 JSON Schema documents and make
  `validate_capsule_document` the authoritative validation entry point. It
  first applies the public structural Capsule Schema and then the strict
  Python semantic pass for unique identifiers, reciprocal evidence bindings,
  cross-references, signature-policy agreement, and lock/checksum equality.
- Limitation: Draft 2020-12 cannot express every cross-record relation over
  JSONL-derived arrays. A generic JSON Schema engine alone is structural and
  may accept a document later rejected by the mandatory semantic pass. The
  root Schema carries an explicit `x-contractcapsule-semantic-validation`
  annotation; no raw-Schema equivalence claim is made.
- Package carriers: the frozen package files remain required. Optional
  `payload/metadata.json` and `evidence/metadata.json` carry only module-level
  extension objects and are omitted without changing identity when those
  objects are empty. They are not treated as new core modules. Unknown carrier
  fields and undeclared files fail closed.
- Evidence trust: bundled CAS bytes are rehashed; Git and external evidence
  receive structural locator/digest validation without network access. The
  loader returns no partial Capsule and performs no Registry or CAS mutation.
- Local filesystem boundary: static symlinks, non-regular entries, traversal,
  duplicate logical paths, and undeclared files are rejected. A concurrently
  hostile process that mutates package directory entries during loading is not
  claimed to be contained by M2; callers must supply a stable local snapshot.

## M2-005 - CAS and Registry immutable publication semantics

- Date: 2026-08-02
- Status: implemented and tested; M2 human exit pending
- CAS commit: payload bytes determine the digest. A canonical envelope stores
  the digest, exact media type, and size. Same-filesystem temporary writes are
  flushed, linked with no-replace semantics, directory-synced, and protected
  by a per-digest advisory file lock so concurrent readers/writers cannot
  observe a link whose durability check later fails. Existing bytes and media
  type are always revalidated and never overwritten.
- CAS authorization: a write creates no read grant. Direct CAS reads default
  deny and require the authorizer to return the exact Boolean `True`; malformed
  or truthy non-Boolean results deny. The published-reference read interface is
  `Registry.get_blob`.
- Registry tables: `publications` has a unique `(capsule_id, version)` key;
  `evidence_references` has publication/evidence and publication/ordinal
  uniqueness; `digest_grants` is foreign-keyed to a specific evidence row.
  Foreign keys are enabled and no replace, public update, or public delete API
  exists.
- Publication transaction: strict model revalidation, authorization, and an
  explicit `BEGIN IMMEDIATE` precede the private CAS integrity/media-type
  check and insertion of the publication, evidence rows, and grants. A failure
  rolls back all SQLite state. A previously written but unpublished CAS object
  remains an unreadable orphan.
- Authorization: Resolver decisions are type-checked and default deny.
  Effective access is the intersection of a trusted Resolver decision and all
  relevant Capsule access-policy constraints. A blob read succeeds through
  the union of individually valid published references, with stored
  publication, grant, digest, media type, and payload revalidation.
- Republish: exact immutable replay reauthorizes, compares every persisted
  publication/signature/evidence/grant field, returns the original timestamp,
  and writes nothing. Same ID/version with a different digest is a version
  conflict; any other immutable mismatch is a publication conflict.
- Boundary: SQLite and filesystem CAS cannot form one cross-resource
  transaction. M2 guarantees fail-closed Registry visibility and permits
  unreadable orphan blobs; it does not provide deletion, revocation,
  cross-tenant isolation, dynamic roles, distributed authorization, or
  production signature verification.

## M2-006 - Verified M2 technical commit

- Date: 2026-08-02
- Status: technical work complete; human exit pending
- Commit: `fac9522a4abd7da85a794b5fcbf59ec012259b8b`.
- Message: `feat: implement M2 canonical storage core`.
- Verification before commit: 172 M2 model/loader/CAS/Registry/property tests,
  30 M1 formal tests, and 206 cumulative tests passed. Ruff, mypy, uv lock,
  extended complexity, Schema consistency, frozen-hash, literature/JSONL
  structure, whitespace, and tracked-artifact checks passed.
- Audit note: the first one-line literature and JSONL parser commands had
  shell/Python quoting errors and exited 1. Corrected commands exited 0; no
  record was changed by the failed commands. Both failures remain disclosed in
  the M2 report.
- Boundary: this local commit was not pushed, merged, or used to start M3.
  Unit/property/formal tests are engineering evidence, not empirical results.

## M2-007 - Author-audit Schema parity remediation

- Date: 2026-08-03
- Status: **M2 IMPLEMENTATION CONDITIONAL PASS**; remediation implemented and
  independently reviewed; M2 exit not formally approved
- Audit baseline: the author audit evaluated starting HEAD
  `78eb719f6ca5dd9b97eb964e6f54a17aa34e028c`, authorized remediation of the
  local static Schema/Python assertion mismatch, and did not authorize M3.
- Finding boundary: the original public `load_capsule()` path remained
  fail-closed. The blocker was static JSON Schema accepting local values that
  the existing Python validation rejected, not a public loader bypass.
- Implementation commit:
  `3b3cb870a05c1af7458268f66da37a9fc5e9474f`. The remediation tightens the
  generated Schema acceptance surface to match existing Python semantics; it
  does not relax Python or change canonical identity, CAS, Registry,
  authorization, exact republish, or any Evidence mode.
- Authorized constraints: add `minItems: 1` for `Atom.scope`,
  `ReplacementContract.target_effects`, and `protected_invariants`; emit an
  ECMA-safe exact Git-path pattern matching the Python safe-relative rules; and
  emit HTTPS/DOI/URN URI lexical families compatible with Python `urlsplit`
  scheme normalization and portable DOI/URN Unicode whitespace semantics.
- Git-path boundary: reject empty and absolute paths, leading drive prefixes,
  backslashes, NUL, empty segments (`//` or trailing `/`), and literal `.` or
  `..` segments in leading or interior positions.
- URI boundary: static Schema checks the HTTPS/DOI/URN lexical family. The
  authoritative Python semantic pass retains application-level parsing,
  including canonical HTTPS host/netloc, credentials, port, query, fragment,
  percent, slash, and dot-segment rules. Raw Schema is not claimed equivalent
  to the full Python validator.
- Schema generation: all eight Schema artifacts regenerated deterministically;
  four changed (`capsule`, `evidence-plane`, `replacement-contract`, and
  `semantic-payload`) and four remained byte-identical.
- Loader regression: persistent raw-byte public `load_capsule()` tests reject
  `NaN`, `Infinity`, and `-Infinity` at the strict parser boundary.
- TDD Red evidence: the initial focused run exited 1 with 13 failed and 16
  passed; Git newline exact-anchor exited 1 with 2 failed and 26 deselected;
  HTTPS normalization exited 1 with 3 failed and 28 deselected; URI portability
  exited 1 with 4 failed and 39 deselected; URI trailing newline exited 1 with
  2 failed, 6 passed, and 35 deselected. A mistyped `-k newline_text` selected
  zero tests and exited 5; it changed no data and remains recorded as a command
  error.
- Green evidence at the remediation commit: 218 M2 tests passed (models 72,
  loader 57, Schema parity 43, CAS 18, Registry 22, property 6); targeted
  Schema tests passed 45; M1 formal tests passed 30; M0 locks passed 4; the
  full suite passed 252 = 218 + 30 + 4. Final runs had no skip, xfail, or
  deselection. Ruff, mypy over 24 source files, the 38-package lock check,
  complexity, whitespace, and both frozen hashes all passed with Exit 0.
- Review: independent specification and code-quality reviews approved the
  technical remediation after two review/fix loops. AI-assisted review does
  not substitute for author gate approval.
- Unchanged governed inputs: CCS-2.1, the frozen execution plan,
  `research/protocol.md`, dependency declarations, and `uv.lock` are unchanged.
- Claim boundary: C2-C5 empirical evidence, TER/PIP/BSR observations, baseline
  advantage, and cross-agent generality remain absent. Context Codec remains
  high overlap.
- Pending decision: the author must formally reapprove or reject the M2 exit
  gate. M3 remains unauthorized and has not started.

## M2-008 - M2 remediation accepted and exit gate approved

- Date: 2026-08-03
- Status: **M2 REMEDIATION ACCEPTED; M2 EXIT GATE FORMALLY APPROVED**
- Approved HEAD: `eec2c1fd173748f181dc8b672b3be320035426a8`.
- Decision: the author accepted the local Schema/Python parity remediation and
  the final verification evidence, including the 252-test cumulative suite,
  static and structural checks, frozen-digest verification, and independent
  specification and quality reviews.
- Accepted engineering scope: non-empty `Atom.scope` and replacement target
  effects in module/root Schema; ECMA-262-compatible Git relative-path lexical
  assertions with Python defense in depth; portable external-URI lexical
  assertions plus mandatory Python URI semantics; and raw-byte public-loader
  rejection of `NaN`, `Infinity`, and `-Infinity`.
- Claim boundary: approval closes the M2 engineering gate only. It establishes
  no C2-C5 empirical result, TER/PIP/BSR observation, baseline advantage, or
  cross-agent generality. Context Codec remains a high-overlap neighbor.
- Immutability boundary: this governance decision does not alter CCS-2.1, the
  frozen execution plan, `research/protocol.md`, implementation code, Schema,
  tests, dependencies, or `uv.lock`.
- Next-module boundary: M3 is not authorized by this approval and has not
  started. A separate author instruction is required before M3 work.

## M3-001 - Early start authorization and unchanged semantic scope

- Date: 2026-08-09
- Status: implementation authorized; M3 human exit gate pending
- Baseline: `a0dc9c72b210e41699aad6377a21642cac75abf0` on the isolated
  `codex/m3-builder` worktree.
- The author authorized M3 before the frozen 2026-08-13--2026-08-16 window.
  This is recorded as **schedule acceleration without semantic scope change**.
- The authorization covers only source ingestion, deterministic atomization,
  source-map/evidence binding, trust classification, quarantine/promotion, and
  the M2-backed build/load/publish path. M4 eligibility, ranking, dependency
  closure, conflict resolution, and view compilation remain unauthorized.
- CCS-2.1, the frozen execution plan, and the frozen research protocol remain
  read-only. No protocol or identity-semantics revision was needed.

## M3-002 - Source-grounded trust boundary implementation

- Date: 2026-08-09
- Status: technical implementation complete; author review pending
- Technical commit: `232b475ce302e06e9292362ffb12e530a5672548`.
- Implemented deterministic source snapshots and parsers, immutable Git/CAS/
  external evidence bindings, source-drift checks, secret scanning before
  storage/rendering, T3 quarantine for generated candidates, externally
  verified approval promotion, and a public-loader/M2 Registry publication
  boundary.
- The approval adapter is explicitly a local HMAC test/research trust adapter;
  it is not a production signature-security result. Git and external evidence
  are checked offline and are not remotely fetched.
- Verification: focused M3 suite 28 passed; cumulative suite 280 passed;
  M1 formal cases 30 passed; Ruff, mypy, lock, complexity, whitespace, and
  frozen-hash checks passed with Exit 0. No skip, xfail, or deselected test was
  used.
- Research boundary: this is engineering evidence for source fidelity and
  trust gating only. It does not add C2-C5 empirical results, TER, PIP, BSR,
  baseline advantage, or cross-Agent generality.
- Human validation state remains pending; the technical commit was not pushed,
  merged, or used to start M4.

## M3-003 - Read-only exit audit failure and root-cause remediation

- Date: 2026-08-16
- Status: **M3 READ-ONLY AUDIT FAIL ACCEPTED; ROOT-CAUSE REMEDIATION COMPLETE;
  HUMAN EXIT PENDING**
- Audit target: `fbe4ee112809c0de92acdb3a525d0d7a56bb4aa0`.
- Root cause: build-time quarantine/approval checks were not a mandatory,
  authoritative policy gate for every public P0/P1 publication path. Direct
  `Registry.publish()` could establish a structurally valid publication without
  the M3 Evidence/approval proof.
- Decision: every fresh P0/P1 publication, including marker-stripped input,
  must cross one Registry-enforced gate. The configured trust root is immutable
  service-composition state; authorization, loader/package, CAS, candidate,
  Evidence, source, approval, expiry, scanner, and lifecycle conditions are
  rechecked inside the Registry write transaction before insertion.
- Trusted source boundary: `generated=False` is non-authoritative. Public
  ingestion remains T3. T2 requires an explicitly composed deterministic Git
  collector bound to the same trust root, immutable repository/commit/path,
  parser profile, snapshot, and content digest.
- Technical commit: `3352147c39be3f989d1370fbaa26f5b0ad0fba8d`
  (`fix: enforce M3 publication trust gate`).
- Claim boundary: the original M3 exit-candidate conclusion was overturned and
  remains preserved as history. The remediation is engineering evidence only;
  M3 human approval is pending and M4 remains unauthorized.

## M3-004 - Author-authorized M2 test-contract migration

- Date: 2026-08-16
- Status: migration complete; M3 human exit pending
- Frozen-semantic determination: CCS-2.1 and the M2/M3 frozen plan require
  canonical identity, CAS integrity, lifecycle, Principal authorization, and
  immutable Registry behavior, but do not promise that a fresh P0/P1 version
  remains publishable without M3 proof after the M3 trust gate exists. The 17
  failures all shared that pre-M3 fixture setup; none represented a distinct
  frozen semantic conflict.
- Author decision: migrate only the publication setup to the actual trusted M3
  path. Do not add a legacy production bypass, lower P0/P1 to P2, construct
  trust artifacts manually, reduce Hypothesis generation, or alter the original
  Registry/CAS/lifecycle/Principal/immutability assertions.
- Preserved evidence: the strict gate first produced `299 passed, 17 failed`;
  the existing M3 remediation checkpoint produced `55 passed`. The 17 failures
  are compatibility Red evidence, not the original security-test Red.
- Test implementation: the isolated `TrustedM3TestHarness` executes source
  snapshot, Evidence binding, trusted test-root approval, promotion, package
  build/public loader, permit issuance, and Registry final validation. Direct
  no-proof P0/P1 rejection and trusted positive publication remain persistent.
- No frozen baseline, protocol, dependency, lock, or M2 production bypass was
  changed. M3 remains pending author review; M4 has not started.

## M3-005 - Final remediation verification

- Date: 2026-08-16
- Status: **M3 REMEDIATION COMPLETE -- EXIT CANDIDATE PENDING AUTHOR REVIEW**
- Technical HEAD: `3352147c39be3f989d1370fbaa26f5b0ad0fba8d`.
- Governance HEAD checked: `5fe30acb6360f993ca64c8de5c6f680f5006ad81`.
- Verification: Registry 22, property 6, direct negative/positive gate 3,
  M3 integration/security 65, M2 218, M1 formal 30, M0 lock 4, and cumulative
  317 tests passed. Ruff, mypy, 38-package lock, extended complexity,
  governance/JSONL structure, prompt-summary hashes, whitespace, protected
  inputs, ancestry, and both frozen digests passed.
- Test accounting is disjoint: `218 + 30 + 4 + 65 = 317`. No skip, xfail, or
  deselected case was used.
- Claim boundary: this closes the authorized technical remediation only. It
  supplies no C2--C5 empirical result, TER/PIP/BSR observation, baseline
  advantage, or cross-Agent generality. M3 human approval is still pending;
  M4 has not started and remains unauthorized.

## M3-006 - Second exit audit failure and five-finding post-audit remediation

- Date: 2026-08-17
- Status: **SECOND AUDIT FAIL ACCEPTED; POST-AUDIT TECHNICAL REMEDIATION
  COMPLETE; INDEPENDENT READ-ONLY REAUDIT REQUIRED; HUMAN EXIT PENDING**
- Exact start: `6a06866e8594a59a07205fa858cc2ff2ef8e3acf`; isolated branch
  `codex/m3-post-audit-hotfix-1`.
- Technical commit: `b793ef1454a2d1d9f63fe4113c50082396aeeb57`.
- Authoritative-source decision: CCS-2.1 identifies immutable Git evidence by
  repository plus exact commit, path, and digests. Final Registry validation
  therefore resolves that exact trusted Git object inside the write
  transaction; it does not trust retained permit bytes, a caller resolver, a
  working-tree file, or a moving branch HEAD.
- Binding decision: candidate, Evidence, and version tests must recompute valid
  canonical identity and preserve Principal policy so the stable failure comes
  from final M3 validation. Existing production binding logic needed no
  unrelated change; temporary mutations prove each corrected test is sensitive.
- P0 decision: the test-only migration helper may select P0 before approval so
  the real Evidence/approval/promotion/loader/Registry flow covers it. No
  production P0/P1 downgrade, public helper, or property reduction is allowed.
- Attestation decision: insertion already shares the publication transaction.
  Complete counts and insertion-stage failure/retry/replay/tamper tests supply
  the missing evidence; the transaction layer is not rewritten.
- Governance decision: candidate-added ledger rows use only the frozen
  `research_role` and `human_validation` enums. Exact-digest exceptions retain
  pre-enforcement research history but cannot admit new invalid rows.
- Count provenance: Git-object reconstruction produced `280` nodes at
  `fbe4ee1` and `317` at `6a06866`, with exactly 37 added remediation-security
  nodes. A historical 316 count is not independently reproducible and remains
  an unverified intermediate observation rather than fabricated evidence.
- Claim boundary: these are engineering/security tests, not TER/PIP/BSR or
  C2--C5 empirical results. M3 remains pending a new independent read-only
  audit. M4 was not started and remains unauthorized.

## M3-007 - Post-audit remediation final verification

- Date: 2026-08-17
- Status: **POST-AUDIT REMEDIATION COMPLETE; EXIT CANDIDATE PENDING NEW
  INDEPENDENT READ-ONLY AUDIT**
- Verified technical HEAD: `79f7f078d45d6b3b70f56557fdc20bb2f5975f66`.
- Local chain after the audit candidate: `6a06866e -> b793ef1 -> 7a6306e ->
  79f7f07`; all commits descend from the required exact start.
- Final behavior: 13 focused final-gate nodes, 23 Registry tests, 6 unchanged
  Hypothesis/property tests, 219 M2-path tests, 71 M3 integration/security
  tests, 30 M1 formal cases, 4 M0 lock tests, and 1 governance test passed.
- Full result: 325 passed, with no failure, error, skip, xfail, or deselection.
  The five disjoint path partitions sum to `219 + 71 + 30 + 4 + 1 = 325`.
- Node provenance: all 317 node IDs collected from the read-only `6a06866e`
  archive remain; 0 were removed or renamed; 8 exact new node IDs were added.
- Static/governance: Ruff, mypy over 34 files, extended complexity, 38-package
  lock, JSONL required fields, frozen enums, prompt-digest declarations,
  whitespace, protected-file diff, and both frozen hashes passed.
- Preserved failure: the first final static pass exposed four mypy errors and
  four complexity findings. A behavior-preserving helper extraction fixed
  them in `79f7f07`; the focused and full suites were rerun afterward.
- Decision boundary: this verifies engineering remediation only. It does not
  reverse either audit decision, record author approval, add C2--C5 empirical
  evidence, or authorize M4. A separate independent read-only audit is next.

## M3-008 - Author-authorized detached-signature read binding

- Date recorded: 2026-09-05
- Status: **REPAIR IMPLEMENTED AND SECURITY-VERIFIED; NOT EXIT APPROVAL**
- Author authorization: repair M3 detached-signature attestation reading and
  conduct a fresh independent audit. The earlier request to continue through
  M4/M5 does not establish that this failed M3 gate has passed.
- Exact baseline: `7d673372aafaef440f0337b578bd93cdfa0d3260`.
- Technical commit: `dc5e87b79436020f32f858ad62041710cf826947`, branch
  `codex/m3-post-audit-hotfix-2`. Only Registry and its security regression
  test changed: 59 insertions and 2 deletions.
- Root cause: reconstructed stored detached signatures were outside CCS
  canonical identity and were not compared to the existing signature-inclusive
  publication digest authenticated inside the persisted M3 attestation.
- Decision: after trust-root signature verification, reuse the existing loader
  publication projection on reconstructed stored state. Missing, malformed,
  unavailable or mismatched projection data fails closed. Legacy pre-M3 reads
  and the process-local loader/HMAC boundary are not changed.
- Evidence: real public `Registry.get` regression RED before implementation,
  GREEN after, comparison-removal mutation RED, restored GREEN. The independent
  reviewer repeated the mutation in a separate archive and checked all public
  read/use paths and genuine M2-to-M3 database migration.
- Boundary: the repair neither changes A-zone identity nor verifies an arbitrary
  production signature algorithm. It binds the existing publication envelope
  to the configured research trust root. Frozen files and schemas are unchanged.

## M3-009 - Independent audit completed with a new quality-gate blocker

- Date: 2026-09-05
- Status: **INDEPENDENT TECHNICAL EXIT AUDIT FAIL; NEW REMEDIATION AUTHORIZATION
  REQUIRED; M3 HUMAN EXIT OPEN**
- Audited HEAD: `dc5e87b79436020f32f858ad62041710cf826947`.
- Independent reviewer: fresh internal Codex agent
  `m3_september_independent_audit`; requested `gpt-6-astra`, high effort.
  Earlier HTTP 429 attempts did not perform reviews and are not evidence of
  independent approval. No external agent or search plugin was substituted.
- No new security/correctness/compatibility defect was found in the repair.
  Independent tests passed: 219 M2 + 72 M3 + 30 formal + 4 spec locks + 1 ledger
  = 326; all 17 extra diagnostic probes passed separately. Mypy covered 34
  files; default lint, 38-package lock and frozen/protected-file checks passed.
- P2 finding: `.gitignore:11` has unanchored `build/`, so Git-worktree Ruff
  discovery excludes `src/contractcapsule/build/`. Full archive or
  `--no-respect-gitignore` checks fail at `ingest.py:432` with C901 17 > 10,
  PLR0912 17 > 12 and PLR0915 58 > 50. These files are unchanged since `79f7f07`.
- Evidence correction: historical Exit 0 directory checks remain true as
  command observations, but are insufficient proof of whole-source complexity
  compliance. The complete scan's failure is retained and overrides that broad
  interpretation. No threshold or test was weakened to maintain a pass claim.
- Next proposed scope, not executed: correct lint discovery, split only
  `_snapshot_source` without behavioral changes, prove source discovery with a
  regression check, and rerun cumulative verification plus independent audit.
- Full report: `research/module-reports/M3-2026-09-05-independent-audit.md`;
  exact diagnostic source is preserved in its adjacent `.py.txt` evidence file.
- Schedule: G1 is missed; G2 is due today without its prerequisites; G3 is
  tomorrow. None is marked passed. No frozen schedule is changed.
- Author decision: the supplied M3/M4 plan's phase 0 item 5 requires separately
  authorized repair after audit failure. No new production fix is attempted;
  no M3 exit approval is inferred. M4 and M5 remain unstarted.
- Research boundary: engineering evidence only; no formal experiments or
  empirical TER/PIP/BSR, baseline advantage or cross-agent generality results.

## M3-010 - Limited Builder quality remediation authorized

- Date: 2026-09-05
- Status: **AUTHOR-AUTHORIZED M3 REPAIR ONLY**
- Author instruction: correct scan scope, split the function without changing
  behavior, add regressions and repeat independent audit.
- Baseline: `548af1eabcffccf2ffdfd5c89ab9f1e2dbc9a7d8`, existing isolated
  `codex/m3-post-audit-hotfix-2` worktree. The worktree was clean and both frozen
  hashes matched before implementation.
- Allowed technical surface: `.gitignore`, `build/ingest.py`, and two new unit
  regression files. No Registry/trust-policy, schema, dependency, protocol,
  frozen-file, existing-test or next-module change was authorized.
- Approval of this repair is not approval of the M3 exit gate, a merge, or M4.

## M3-011 - Scan discovery fixed and ingestion behavior preserved

- Date: 2026-09-05
- Status: **LIMITED TECHNICAL REPAIR COMPLETE**
- Scan commit: `b6f7608c5ba5f6518465e43100724f89b139eba4`.
- Refactor commit: `2294af30ade13e1aad5507a85976cd80f425c2fc`.
- Root-only `/build/` replaces the broad ignore rule. Actual Ruff consumers
  expose deliberate Builder diagnostics while still ignoring generated root
  build artifacts, including the nested-parent-ignore case.
- `_read_source_content` and `_validate_source_content` extract existing
  statements; original call shapes, validation/error semantics, metadata and
  identity, scans, CAS effects, proof issuance and registration order remain.
- TDD: three discovery regressions failed before the ignore fix and passed
  afterward. Ten characterizations passed before and after the refactor; they
  are not misrepresented as bug RED. Finalized tests also pass against the
  original baseline production archive.
- All 326 original nodes and 26 original test/fixture files are retained
  unchanged; 13 new nodes give 339 committed tests. Full discovered Python
  inventory is 36/36, including all four Builder files. Complexity thresholds
  and all other ignore rules are unchanged; no new suppression was introduced.
- Test-only Mypy/import-lint iteration failures and successful corrections are
  retained in the report, not omitted from the development record.

## M3-012 - Independent quality reaudit passed; human exit remains pending

- Date: 2026-09-05
- Status: **TECHNICAL M3 EXIT REAUDIT PASS; HUMAN EXIT APPROVAL PENDING**
- Target: `2294af30ade13e1aad5507a85976cd80f425c2fc`.
- Fresh task reviewer `m3_lint_scope_task_review`: spec compliance PASS and
  quality APPROVE. Fresh exit auditor `m3_quality_independent_exit_audit`:
  independently reproduced technical PASS; no actionable findings.
- Independent evidence: 13 new + 72 M3 + 219 M2 + 35 formal/locks/ledger = 339;
  all full-suite cases pass. Ordinary and no-ignore lint/complexity, Mypy 36,
  38-package lock, frozen hashes, protected-file and whitespace checks pass.
  Independent os.walk, archive Ruff and worktree Ruff inventories match 36/36.
- Preservation evidence: AST expansion reconstructs the original ingestion
  statement sequence, all old signatures remain, and baseline characterization
  passes. Original-node/file retention was independently checked.
- Independent mutations: broad ignore causes two real diagnostic failures;
  post-CAS validation causes four forbidden-persistence failures; removing the
  prior Registry projection comparison causes its signature regression to fail.
  All changes were restored in the disposable archive; the entire 79-file HEAD
  archive then matched source. All gates reran successfully afterward.
- The 17 supplemental read/Blob/replay/malformed/legacy probes also passed;
  they are not included in the 339 committed-test count. A macOS path-alias
  error in the audit inventory script was corrected and retained as an audit
  setup failure, not a product result.
- Report: `research/module-reports/M3-2026-09-05-quality-remediation.md`.
  Its adjacent `.tar.gz` preserves 24 original audit scripts/logs with a
  recorded digest. The previous failed audit is not rewritten.
- Boundary: no C1-C5 empirical claim, TER/PIP/BSR measurement, baseline result
  or cross-agent generality is established. AI engineering review does not
  substitute for author approval or independent human benchmark truth.
- The frozen schedule and all earlier decisions remain unchanged. The branch
  is retained without merge or push. M4 and M5 have not started; the author
  must approve M3's exit before any next module.

## M3-013 - Author exit approval and M4 start authorization

- Date: 2026-09-05
- Status: **M3 EXIT FORMALLY APPROVED; M4 START AUTHORIZED**
- Author-approved baseline: `4dbf4849c6e125d1cb5ac8d813e4aeb5dc75694d`.
- Author instruction explicitly approves M3's exit and authorizes starting M4
  from that baseline. It accepts the M3 repair/reaudit and evidence records,
  including technical HEAD `2294af30ade13e1aad5507a85976cd80f425c2fc`.
- Fresh baseline verification: 339 cumulative tests passed in 8.41s; worktree
  was clean and both frozen SHA-256 values matched before this governance edit.
- M0-M3 are now author-approved: 4 of 12 modules, not 4 of 12 empirical claims.
- Only approval records change here. Source, tests, schemas, dependencies,
  frozen inputs, protocol and all historical failed audits remain unchanged.
- M4 will branch from this governance-only descendant of the exact approved
  baseline. No merge, push or main-worktree change is authorized or performed.
- The M4 plan's proposed collective-interface extension still needs a separate
  ADR and author approval before implementation. M3 approval and M4 startup do
  not implicitly approve that ADR, M4's eventual exit, or M5.
- Research boundary: engineering acceptance only; no formal experiment,
  empirical TER/PIP/BSR, baseline advantage, or generality result is established.

## M4-001 - Isolated startup after approved M3 exit

- Date: 2026-09-05
- Status: **M4 STARTED IN PREPARATION; ADR APPROVAL REQUIRED**
- Author-approved baseline: `4dbf4849c6e125d1cb5ac8d813e4aeb5dc75694d`.
- M3 approval-record commit and M4 branch point:
  `9743b34168e160878b9b9e8132512c540954f511`.
- Created branch `codex/m4-view-compiler` and worktree
  `.worktrees/m4-view-compiler` from the exact governance descendant. No main
  branch merge or user-facing task creation occurred.
- Baseline environment used `uv sync --locked --offline` without changing
  dependencies; all 339 baseline tests passed in the new worktree (11.49s).
- Read and hash-verified both complete frozen baselines. Existing M1 model,
  source/tests, core schemas, protocol and dependency lock remain unchanged.
- M4 runtime tasks are not started by this preparation record. No M5 work,
  formal experiment, empirical claim or submission gate change is authorized.

## M4-002 - Collective interface coverage ADR proposed

- Date: 2026-09-05
- Status: **PROPOSED; NOT AUTHOR-APPROVED OR IMPLEMENTED**
- The author chose collective interface coverage with an ADR before code,
  minimal local tokenizer/SemVer dependencies, and release-version constraints
  separate from exact `/vN` interface names. The implementation request and
  M3 exit approval retain the ADR gate; they do not automatically accept its text.
- Proposal: `docs/adr/0004-m4-collective-interface-coverage.md`.
- Derived execution plan:
  `docs/superpowers/plans/2026-09-05-m4-view-compiler-execution-plan.md`.
- The proposal separates local capsule admission from collection coverage,
  preserves pre-ranking security checks, exact provider bindings and final
  selected-provider coverage, and requires an explicit M1 singleton comparison.
- M1 and frozen normative files are not edited. Any true frozen-semantic
  conflict requires a separately approved versioned baseline, not a silent ADR
  override. Neither new dependency nor new runtime profile is installed here.
- Next author decision: accept or reject the ADR's concrete text. Technical
  review of the draft cannot substitute for that decision or for M4's exit.
- Draft review found two actionable ambiguities before author submission:
  interface payload membership and root versus dependency lock ownership.
  The proposal now explicitly requires full provider payloads for root task
  interfaces, rejects ambiguous root providers in the exact input collection,
  and reserves consumer-owned A-zone locks for that consumer's dependencies.
  Output witnesses cannot authorize their own initial selection. The token
  cost of full-payload units is disclosed; none of these draft rules is yet
  implemented or recorded as author-approved.
- Scoped rereview marked both findings addressed and found no new explicit
  issue. The author-review draft SHA-256 is
  `be057b3c85dd72c59f13193097b41b96a57a87f55408fcf71dbaf3cd6c2e46e9`.
  This is a proposed-text identity, not an approval record or implementation
  result. Full baseline regression after documentation: 339 passed in 8.49s;
  complete no-ignore complexity and whitespace checks passed.

## M4-003 - ADR-0004 accepted; runtime implementation authorized

- Date: 2026-09-05
- Status: **AUTHOR-ACCEPTED ADR; M4 IMPLEMENTATION AUTHORIZED**
- Exact reviewed proposal: `7eec393659fcb612a4e21b1a9de295d86160e843`, ADR SHA-256
  `be057b3c85dd72c59f13193097b41b96a57a87f55408fcf71dbaf3cd6c2e46e9`.
- The author explicitly approved ADR-0004. Its accepted semantics include
  collective pre-ranking coverage, complete provider-payload membership,
  unique root providers, consumer-owned exact dependency locks, and unchanged
  M1 singleton interface-gate comparison obligations.
- Only ADR acceptance metadata changes; its decision/acceptance-test text and
  both frozen baselines are unchanged. This does not approve M4's future exit,
  authorize M5, or establish any empirical research result.
- Proceed with M4's implementation/test/review sequence. Shared model/protocol
  foundations will be committed before their concrete service consumers; the
  minimal real single-capsule chain is accepted only once those services are
  connected, not by a placeholder compiler. The seven original deliverables
  and their final acceptance obligations remain intact.

## M4-004 - Minimal dependency and offline tokenizer preflight

- Date: 2026-09-05. Status: implementation preflight verified, M4 exit pending.
- Exact new direct pins: tiktoken 0.14.0 and semantic-version 2.10.0; existing
  packages remain at their prior locked versions. Resolved lock has 46 packages.
- Inspected installed official package source and metadata. The native official
  webpage query returned HTTP 502; no alternative search plugin was invoked.
- The official OpenAI o200k_base vocabulary is stored as a B-zone implementation
  resource and matches upstream SHA-256
  `446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d`.
  Its regex/special-token profile is copied from the same pinned official
  constructor; profile SHA-256 is
  `df47711b119989c276e11a040d7a727cb10eff78216c3b1c38614d8aadf63653`.
  License notice and provenance accompany the resource. Runtime code must load
  only local bytes, validate both hashes and never auto-download/repair them.
- SemVer equality includes build metadata in this library; release precedence
  comparison therefore uses Version.truncate('prerelease') on both operands,
  while exact lock equality retains the full published version string.
- Fresh baseline: 339 passed in 8.53s; offline lock check passes. No M4 runtime
  behavior is claimed yet; tokenizer failure/offline behavior needs tests.

## M4-005 - Runtime contract and local-admission checkpoint

- Date: 2026-09-06. Status: bounded technical increments reviewed; M4 incomplete.
- Task1 model/protocol commits `53c6a23` and `036467c`, reviewer
  `m4_1_contracts_review`: PASS. 54 focused /393 accumulated tests; full
  Mypy41 and extended complexity verified. No placeholder compiler.
- Task2 admission commits `8e0d1cc` and `9531920`, reviewer
  `m4_2_admission_review`: PASS after one scoped fix round. Reviewer initially
  exposed cross-task-path scope conjunction and malformed identity sorting.
  Both were reproduced through real Registry tests (8 RED), corrected (13
  added GREEN), and independently marked addressed. The entire task has105
  cases and the cumulative suite498 (main agent rerun12.87s).
- Complete input projection includes immutable publication signature fields,
  but omits derived/runtime sidecars, registry publication time and expected
  output digest. This prevents output/input digest recursion and distinguishes
  transport metadata from reproducible compiler inputs.
- Local admission is not whole-provider coverage; zero/partial atom membership
  stays explicit. The later graph/compiler must enforce complete provider units,
  native evidence checks, actual unauthorized-ranker isolation and locked replay.
- Date risk: original G1/G2 dates are missed; G3 is not passed. No formal
  experiments or claim/schedule revision is performed. M5 remains unstarted.

## M4-006 - Deterministic ranking and strict-input review

- Date: 2026-09-06. Status: Task3 reviewed; complete M4 compiler still pending.
- Commits `60b45eb` and `6bbcb92`; implementer m4_3_fts_ranker, independent
  scoped reviewer m4_3_rank_review. Final task spec PASS /quality APPROVE.
- Real in-memory FTS5/BM25 ranks every admitted formal atom, inserts stably,
  literalizes query words and uses parameterized SQL. No persistent vector/
  keyword index or permission decision is introduced in the ranker itself.
- Concrete frozen services exposed a Task1 static typing defect: Protocol
  metadata declared writable attributes. Only metadata declarations became
  read-only properties, preserving all service method signatures and frozen
  composition. Full Mypy consumer tests verify the correction without Any casts.
- The review found serialization could repair malformed nested extension keys
  or drop unknown Validity fields before checking. Main-agent diagnostics
  confirmed both. Six genuine regression failures preceded the fix, which now
  validates the original value tree before canonical duplicate comparison.
- Final38 focused /536 cumulative tests reported passing; main focused38,
  full Mypy49 and complete complexity verified. Exact prior schemas/models/
  dependencies remain unchanged. Earlier 529 and528 counts are intermediate,
  not discarded failures or additional experiments.
- One handoff received HTTP429 after the commit existed; report-only resumption
  inspected existing artifacts rather than reimplementing. No external CLI,
  search plugin, empirical measurement or M5 work occurred.

## M4-007 - Graph, token/render and native evidence implementation checkpoint

- Date recorded: 2026-09-06. Status: implemented service increments; independent
  review and complete compiler acceptance pending.
- Graph commits `211ffa0` and `9dc9112`: 85 focused /621 cumulative tests;
  version constraints, exact provider locks, presence/unit distinction and
  mandatory closure/conflicts. Names without known node types are retained as
  missing obligations; no capsule-name heuristic or fake cyclic digest proof.
- Counter/render commit `396a9f4`: 40 new tests, cumulative661. Local pinned
  tokenizer profile/BPE only; total text accounting; exact P0 and structural
  P1 including signed extensions; P2 exact excerpt, explicit source expansion.
- Evidence commit `73f99ae`: 18 new tests, cumulative679; reauthorization,
  Registry projection, native content/span digest and secret gates. Controlled
  external mode uses configured local snapshots and never runtime network.
- Task4 received only local review while dispatch was unavailable. Task5/6
  used the disclosed local fallback. None was called independently approved.
- Internal dispatch is available at resume: m4_services_backlog_review conducts
  a fresh read-only review of these services while m4_integration_implementation
  implements the absent compiler/manifest integration in disjoint files.
- Resume target is exact `73f99aebe519e3b0857c9df5fbbeae99e06ff68c`. No original
  test/schema/frozen baseline change is authorized. G1/G2 are not passed, G3
  remains unapproved; M4 incomplete and M5 unstarted.

## M4-008 - Independent Service Findings and Scoped Repairs

- Date: 2026-09-06. Status: fixes implemented; independent rereview pending.
- Reviewer `m4_services_backlog_review` independently reproduced three P1
  blockers at73f99ae: foreign graph declaration ownership, Git locator drift
  from its approved source-map, and Git promisor lazy-fetch side effects.
- Repair `ed7feae` enforces declaration ownership, validates approved locator
  metadata and real structural anchors, and uses M4-only offline Git reads.
  No M3 ingestion behavior or frozen file is modified. Nine regression nodes
  pass; the original report, exact diagnostic and honest RED history survive
  in `research/module-reports/M4-services-independent-review.md` and related files.
- An initial RED set included a setup already rejected by Registry; it is not
  counted as a demonstrated vulnerability. A legacy-anchor positive/negative
  check and exact declaring release coverage complete the regression set.
- Passing local repair tests is not an independent approval. Final rereview
  must verify all three findings against the repaired exact candidate.

## M4-009 - Integrated Compiler Candidate and Verification Handoff

- Date: 2026-09-06. Status: implementation delivered, independent exit pending.
- Compiler commit `ccabe4e` connects real Registry, admission, rank, graph,
  offline counter, renderer and native evidence. It adds locked replay, safe
  manifests, current reauthorization and the independent B-zone schema.
- Candidate `2ce16535ece97733404e91715bb2b7586b54de20` includes the explicitly
  planned ninth-schema inventory adaptation. Only the old directory-set
  assertion is extended; the eight core Schema bytes, eight equality checks
  and original339 test IDs remain. This qualifies M4-007's broad preservation
  shorthand without weakening core identity or removing a regression.
- Controller clean-archive verification: 235 frozen tests, 745 full tests,
  30 formal fixtures; 70/70 file discovery; both Ruff/complexity scans; full
  Mypy70; offline lock/build/wheel checks. Six scoped injected faults are caught.
  The full745 comprises retained339 and new406; these are engineering cases.
- Initial archive tests rejected the macOS /tmp alias; the harness now uses
  resolved /private/tmp without relaxing product checks. Preserve initial
  failures and the corrected targeted P1 mutation alongside final output.
- Independent review is not inferred from the clean archive. Existing agents
  returned their reports, but final continuation lacked a callable dispatch/
  follow-up tool. No external CLI/plugin or user task creation bypass was used.
  Exact audit obligations are saved in M4-final-audit-handoff.md.
- Update C2/RQ1/RQ2/C5 engineering evidence only. Formal completion remains
  M0-M3 (4/12), not5/12. Independent M4 audit and author exit still required;
  G1/G2 are missed, G3 unpassed, no schedule waiver, no M5 or formal experiments.

## M4-010 - Independent Exit Audit Returns Request Changes

- Date: 2026-09-08. Technical2ce1653 and governancecd6cfcf were unchanged and
  clean at audit start/end. Both frozen hashes match. Native internal dispatch
  now works; the prior dispatch-unavailable condition is not the current blocker.
- Independent service rereviewer `m4_services_backlog_review`:9 persistent
  regressions pass; Git locator binding and offline reads scoped PASS. The
  original foreign-source examples are fixed but a denied declaring-owner
  occurrence of a shared atom still imports an edge. Graph finding stays open.
- Fresh independent reviewer `m4_exit_independent_audit`:235 frozen/745 full/
  30 formal pass; full static/type/complexity/schema/build/lock gates pass;
  actual70/70 inventory and original339 retention verified. Ten real fault
  mutations are caught. Final11 additional diagnostics have2 failures/9 passes.
- New compiler findings: fixed compression-class budget precedence depends on
  replacement-ranker ordering, and late revocation leaves denied IDs in the
  public failure manifest even though content and handles are empty.
- Stable pending repair IDs: M4-R1 owner admission(P1), M4-R2 fixed allocation
  order(P2, reviewer IA-M4-01), M4-R3 revoked failure projection(P2, IA-M4-02).
  All require itemized author approval. No implementation/repair branch is
  created. Public models, dependency pins and core/frozen identities stay fixed.
- One reviewer turn hit429 and resumed the same artifacts without overwriting
  results. It completed; all execution sessions ended. Independent reports and
  exact diagnostic/log evidence are preserved under M4-2026-09-08 reports.
- Controller confirmations and artifact checks are separately labeled and not
  treated as independent approval. Audit outcome is REQUEST CHANGES, not a
  waiver based on745 passing tests. Only governance files change after audit.
- M4 remains before author exit; formal progress4/12. G1/G2/G3 dates are past,
  no all-gates approval or schedule change is inferred. M5 and formal
  experiments have not started. Next action: obtain approval for named repair IDs.

## M4-011 - Author Approves R1, R2 and R3; Implementation Checkpoint

- Date recorded: 2026-09-08. The author's direct instruction approved M4-R1,
  M4-R2 and M4-R3 and requested repair work. This approval predates the code
  changes; this durable record is appended after their technical commits.
  It is not M4 exit approval, M5 authorization or approval for unrelated findings.
- Isolated branch/worktree: codex/m4-exit-remediation, from exact4458527.
  This retains the completed audit governance; source/tests/schemas/dependencies
  are byte-identical to audited2ce1653 at the branch point. Original M4 worktree
  remains at4458527. No merge/push or frozen baseline change.
- R1 commit19689c8: exact admitted declaring-owner guard and six regressions;
  RED4failed/2passed, GREEN6 and combined64; cumulative751. Graph stamp1.0.1.
  Original reviewer independently marked scoped R1 PASS after64 tests and
  old-guard mutation (4expected failures), then fresh6pass. This is not full exit.
- R2 commite31a894: stable compression-class assembly, class-internal rank
  preservation and four regressions; genuine corrected RED3failed/1passed,
  GREEN4/combined59; cumulative755. Compiler stamp advanced to0.1.1.
  Initial P4 TTL and same-class budget setup failures are retained and are not
  counted as three additional implementation defects. Only test fixtures changed.
- R3 commitbb1d56d: reauthorize failed transactions and withhold invalidated
  public identity projection; eight more cases including partial revocation,
  malformed snapshots, rank/budget/conflict failure combinations and positive
  unchanged authorization. RED6failed/6passed across the combined repair file,
  GREEN12/combined67; cumulative763. Compiler output/stamp now0.1.2.
- Withheld manifests retain only safe caller metadata, stable compiler stamp,
  a count of invalidated prior capsule snapshot entries and zeroed/redacted
  token detail. That count is not the number individually revoked; token zero
  is not a measurement of real work. Internal transaction state is not deleted.
  Ordinary still-authorized budget failures keep real attempts/counts.
- Only graph.py, session.py, manifest.py and two new regression files change.
  Public call shapes and every existing schema byte remain unchanged; explicit
  output service versions change to distinguish corrected replay semantics.
- Exactbb1d56d is under independent combined reaudit. Local763passes and static
  checks are not independent PASS. Remaining final evidence and governance
  results will be appended. M4 author exit remains pending; M5 unstarted.

## M4-012 - R1-R3 Combined Technical Reaudit Passes

- Date: 2026-09-08. Independent integrated repair/exit reviewer
  m4_exit_independent_audit gives PASS(technical) for exactbb1d56daecbc31240b5ea1371378c50e63dd9c4b.
  All three authorized findings are addressed; no unresolved issue was found
  in their scope and reviewed compiler interactions. Old failed audit reports
  remain unmodified evidence for their old targets.
- Independent full763(33.03s),frozen235(16.70s),formal30; all745 old nodes plus18
  new cases; Mypy72; actual72/72 scanning; Ruff/complexity ordinary/no-ignore;
  offline46-package lock, all9 schemas, build and wheel resource checks PASS.
- Exact old R1/R2/R3 methods restored in disposable processes produce4/3/6
  genuine behavioral assertion failures. Original two compiler diagnostics
  fail on4458527 and pass onbb1d56d. Four extra interactions cover replay-time
  revocation, raw reauthorization errors, truthful authorized P1 budgets and
  internal transaction preservation. These are not formal research experiments.
- Controller final763(33.14s),frozen235(16.69s),formal30 and artifact checks
  agree; they are recorded separately, not used as independent approval.
- Archive: M4-2026-09-08-remediation-evidence.tar.gz,80files, SHA256
  20e6cb48077c76dc475d6a861f6382ac4f47089ad7fc43b5e16251d447be714b.
  Reports are copied byte-for-byte; failure logs are losslessly retained. No
  source copy, cache, fixture private key or generated database is exported.
- Only final governance documents/ledger/evidence follow the technical target.
  The original M4 and root worktrees remain untouched. No merge/push.
- Stop at the separate author M4 exit gate. R1/R2/R3 authorization and technical
  PASS do not advance formal progress beyond4/12. No M5 or schedule/G1-G3 waiver.

## M4-013 - Author Exit Approval and M5 Startup Authorization

- Recorded: 2026-09-09. In the preceding planning turn the author explicitly
  approved entering M5 after being told M4 required the separate exit decision;
  the author now requests execution of that M5 plan. This closes M4's author
  exit at technicalbb1d56daecbc31240b5ea1371378c50e63dd9c4b and governance
  1aeeb116835fc4b9656dd81107a79e6a0afab19a. No new technical changes intervene.
- Independent M4 technical PASS and exact evidence are retained. Fresh startup
  regression on1aeeb11:763 passed in32.94s. Both frozen hashes still match.
- Formal approved-module progress is now5/12 (M0-M4,41.7%). This approves
  bounded engineering evidence only, not a benchmark result or submission claim.
- The author selected signed-core x-* execution extensions and Docker isolation
  for M5. The plan separately requires proposed ADR-0005 text to receive
  independent review and author approval before semantic implementation.
  M5 startup is not advance approval of that ADR, runtime execution approvals,
  M5 exit, M6, revised study scope, or revised deadlines.
- This governance-only commit precedes the new codex/m5-validation-swap
  worktree. No merge/push and no source/test/schema/dependency edits here.
- G1/G2/G3 original dates are past and their gates remain unsatisfied; retain
  RQ3 and research integrity rather than backdating passes or weakening tests.

## M5-001 - Isolated Startup and Proposed Execution Profile

- Date: 2026-09-09. Branch codex/m5-validation-swap starts at exact M4
  approval3bcdbc638de4c10e30fc7dee666e2517450bf1f5. M4 is author-approved;
  M5 startup is authorized with the separate ADR-0005 approval gate intact.
- Fresh new-worktree baseline763passed37.83s; locked offline environment46
  packages. No production/test/schema/dependency file is changed in this phase.
- Proposal198616e contains ADR-0005 and the derived seven-task M5 plan. It
  describes signed clause/test bindings, execution authority separate from
  publication, trusted isolated observations, independent view validation,
  local action/pointer/receipt transactions and guarded rollback. It is not
  adopted semantics until the exact reviewed text receives author approval.
- Docker29.5.2 and local Linux/arm64 image090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203
  were inspected without a pull. A no-network/non-root/read-only/resources
  probe passes; initial interface-name assertions failed because the kernel
  exposes disabled tunnel templates. Actual active-interface/routes and Docker
  configuration were checked instead; original isolation flags remain fixed.
- Only disposable preflight containers were removed, with no persistent user
  data. No candidate test program, actual Agent or M5 behavior was executed.
- Independent document review is requested; full implementation remains behind
  ADR approval. Formal progress5/12; no G1-G3 waiver, M6 or formal experiment.

## M5-002 - Proposed ADR Review Ready for Author Decision

- Date: 2026-09-09. Independent review of198616e requested four clarifications:
  unconditional high/critical activation approval, staged preconditions,
  subject/checker Docker artifact/result-channel separation, and exact complete
  differential snapshots/operands with one pair-level result.
- Revised exact2842a13ddc3e1bb29479017a50e4eae5ad6f239b addresses all four.
  The same reviewer returns READY FOR AUTHOR APPROVAL with no new blocking
  contradiction in the revised scope. No runtime code or schema was changed.
- ADR SHA256: da92462f397a82a6d5c2a2320b6ab98280f5af69edc538ed09ac6533e3115687.
  Plan SHA256: afaf6ebd8d8edc2c16afcff222c5389111e984e3cc22749def15e27deee26b83.
- Original report SHA256:834c7e7ad3572b4c6a7ea1838270042c7b322dfa25f36c74a631c7b1c8f42e89;
  rereview SHA256:6d2b19b9b10499872a37542729eaa6742ebfaf6080f48b2c18091203cde180aa.
  Reports are preserved byte-for-byte. Reviewer ran no tests or Docker;
  controller's inherited763-test results are not represented as review results.
- Post-proposal controller regression763PASS33.20s; Ruff/Mypy72/lock/hash checks
  pass. No M5 feature/behavioral or empirical result is claimed.
- ADR-0005 remains PROPOSED. Stop for exact-text author approval before M5-1
  semantics. No M5 exit, M6, experiment, merge/push or schedule waiver.

## M5-003 - Accepted ADR and Task1 Recovery Record

- Recorded2026-09-10. The author approved the exact reviewed ADR-0005 after
  the readiness report and explicitly requested continued execution of M5.
  Acceptance is committed at104e665f659879d3398a04cdb0425e446653b633;
  the approved proposal is2842a13ddc3e1bb29479017a50e4eae5ad6f239b.
  The acceptance metadata changed only status/approval paragraphs. Accepted
  file digest:c4457f5da29903261ea7ce58c68e28c43cbdfb74eb55e70a8ff5c1d1617921a0.
- The intended decision-log patch failed earlier, so this entry supplies the
  missing durable decision link. The104e665 AI ledger row mistakenly put the
  ADR file digest in its commit field and recorded an incorrect prompt hash.
  The old row remains untouched; an append-only correction identifies it by
  raw-row digest and supplies exact corrected fields. Its timestamp was a
  controller-entered value, not verified run metadata.
- The initial M5-1 worker produced only an unfinished test with fallback
  missing-import values; repeated waiting did not produce a source implementation
  or task report. It was interrupted, and m5_1_recovery now owns the bounded
  task. The unfinished test is preserved in ignored task scratch before repair.
  Missing imports/fixture faults are not behavioral security RED evidence.
- Continue M5-1 with real publication/artifact-byte tests and the accepted
  trusted execution boundary. Approval verification is reusable; operation
  redemption/idempotency belongs to the later durable state owner, as required
  by the accepted prepare/activate transaction semantics. No fake in-memory
  once-only validation is a substitute for transaction-level replay protection.
- No M5 feature is yet complete; all M6/experimental/module exit gates remain.

## M5-004 - Executable Binding Task Reviewed

- Date2026-09-10. Task1 technicalbbf031d8d83cfdf055ab6fc1a4aa617c7c8fc614
  implements strict execution/profile/phase/expectation and clause mappings,
  Registry-backed publication comparison, local package-byte snapshots and
  separate reusable HMAC approval verification. It adds46tests; full809 pass.
- Independent task reviewer m5_1_task_review gives spec PASS and quality PASS
  with no actionable finding, plus10focused independent diagnostics. The
  implementation report and independent review remain separate evidence.
- Task2 begins at31e7b49. It will add independent view verification and the
  narrow authenticated m5_records journal needed by its planned persisted
  reports. Action/ticket/pointer tables remain Task5; no publication mutability.
- The journal is trusted-host result authority, separate from approval keys;
  a public transport report cannot issue or authenticate itself. No Task2-7
  completion, M5 exit, M6 or empirical result is claimed by this checkpoint.

## M5-005 - Independent Validation and Report Journal Implemented

- Date2026-09-10. Task2 technicalc4fa931/917e702 adds the shared m5_records
  authenticated journal and request-scoped ValidationService. New report model
  construction conveys no authority; stored exact HMAC record kind/scope/subject
  and payload must verify. Publications/core/model/schema bytes stay unchanged.
- Direct checks require P0/P1/root membership, closure/conflicts, native bytes
  and handles, neutral render and full token counts. Compiler replay is only
  supplemental. Current-time admission is separate from reconstruction as_of.
  Failed authorization reports withhold identity and measurement metadata.
- Implementation reports48focused/857full passes, Mypy86 and ordinary/no-ignore
  Ruff/all4complexity scans; membership/HMAC bypass mutants fail actual tests.
  The report preserves fixture mistakes separately from genuine behavioral REDs.
- Independent Task2 review is pending at exact917e702. Tasks3-7 remain; no
  behavioral run, Docker subject execution, active pointer or M5 exit result.

## M5-006 - Independent Validation Task Reviewed

- Date2026-09-10. Independent review gives spec PASS/quality PASS for Task2
  exact917e702. No actionable finding; three targeted diagnostics reject
  unavailable expansion with a lying compiler, forged matched-digest payload
  and copied signed row under another record ID. No broad suite rerun is
  attributed to the reviewer;857full passes remain implementation evidence.
- Report M5-2-independent-review.md is preserved with its own exact target.
  Task3 begins atf161910 to implement separate behavior/differential evaluation.
  Expected report kinds/subjects and fresh effect-time validation remain
  integration obligations. No Task3-7 outcome/M5 exit/M6 approval is implied.
