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
