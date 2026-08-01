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

## M1-006 - Preregistered analysis protocol

- Date: 2026-08-01
- Status: frozen candidate pending G0 author approval
- Decision: freeze RQ1-RQ4, primary and secondary outcomes, conditions,
  ablations, units of analysis, inclusion/exclusion rules, infrastructure-only
  retry policy, and statistical test families in `research/protocol.md` before
  any full experiment.
- Statistics: task-level paired aggregation, task-cluster bootstrap intervals,
  exact McNemar for paired binary outcomes, paired permutation tests for
  numeric/rate outcomes, preregistered Wilcoxon sensitivity conditions, effect
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
