# Independent Task 1 review

Date: 2026-09-10. Reviewer: delegated independent Codex reviewer, distinct from
the Task 1 implementer. Scope: M5-1 executable contract and authority bindings
only; read-only repository review. Verdict: **PASS (Task 1 technical scope)**.
No blocking or actionable code defect was found in the reviewed scope. This
does not approve M5 exit, M6, a merge, a revised schedule, or formal experiments.

## Exact evidence target

- BASE: `104e665f659879d3398a04cdb0425e446653b633`.
- Reviewed implementation: `bbf031d8d83cfdf055ab6fc1a4aa617c7c8fc614`.
- Worktree: `/Users/litmus/Documents/Contract Capsule/.worktrees/m5-validation-swap`.
- Eight added source/test files, 1,352 insertions. The supplied review diff is
  byte-identical to `git diff BASE HEAD`; both have SHA-256
  `62271ff7895b8ff7d8955a10f68e509dc026d9d794e97a900c22ec143686c03c`.
- During review the controller committed governance as
  `31e7b49b2533a1366978ef6c272707c3812ea56d`. Its changes are only five research
  documents/ledger files. `git diff --exit-code bbf031d... 31e7b49... -- src tests
  schemas pyproject.toml uv.lock <both frozen files>` returned 0. Thus the
  independent diagnostics below exercised implementation bytes identical to
  the stated technical target. Initial dirty decision-log/ledger edits were
  controller-owned and were not touched by this reviewer.

## Alignment and reviewed inputs

Read complete AGENTS.md, CCS-2.1 and frozen execution plan; Task 1 brief,
implementation handoff and full review diff; accepted ADR-0005; derived M5
execution plan; and latest decision-log entries through M5-003. Inspected the
existing shared model/canonical encoding, package loader and Registry read
boundaries to verify that the new calls invoke actual checks rather than
metadata-only facades. Used code-review-and-quality for separate correctness,
readability, architecture, security and performance assessment.

Both frozen hashes matched initially and on final recheck:

- CCS-2.1: `aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c`.
- Frozen plan: `7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0`.

The accepted ADR is already author-approved; no repeated approval is required
for this review. ContractCapsule manages immutable, evidence-grounded context
units whose behavioral replacement is verified. Its contribution depends on
target effects, protected invariants and bounded spillover together with
traceability and atomic replacement, beyond summary/RAG/memory representation.
Task 1 prepares executable bindings and approval evidence; it does not yet
prove those later runtime behaviors. The seven core modules and twelve frozen
invariants are retained because no existing core/schema is changed. In
particular Task 1 contributes engineering prerequisites to invariants 1, 8,
11 and 12; it does not claim completed activation-boundary or rollback tests.

Original M5 dates were August 22–24; September 10 is 17 days after that window.
G1/G2/G3 dates are past, without a gate or schedule waiver. No Task 1 input,
hash, authorization or missing review-skill blocker was identified.

## Spec compliance review

PASS for the bounded Task 1 contract:

- Strict extension parsing preserves M2 acceptance. `validate/contracts.py:29`
  revalidates task/request/budget values, then reads the frozen extension
  through strict runtime models without serializer coercion (`:55`). Profile,
  field, expectation presence, duplicate IDs and complete clause coverage are
  checked. `:136` onward validates exact clause text hashes, role, phase,
  expectations and probe snapshot variants; `validate/models.py:88` rejects
  wrong expectation-field variants rather than accepting null placeholders.
- `validate/contracts.py:68` retrieves both publications from the real Registry
  under the principal and compares the full core/signature/status projection.
  `:80` checks the exact old reference, replaces/rollback pointer, accepted old
  interfaces, new root interfaces, source repository, tenant and effective-risk
  repeat count. Dependency providers cannot substitute for the root here.
- `validate/artifacts.py:62` uses an explicitly configured package mapping and
  existing loader, compares its core/signature to the Registry projection, and
  rehashes actual test bytes. `:33` opens regular files without following final
  or artifact-directory symlinks and returns byte snapshots. Frozen core paths
  constrain the relative names. Later mutable paths are not execution inputs.
- `validate/contracts.py:198` verifies the complete resolved test set against
  declared paths/kinds/digests and reciprocal checksums and hashes bytes again.
  `:183` requires each invocation's declared entry/helper subset. `:234`
  separates executor/probe artifacts from checker artifacts by ID, folded path
  and content digest. Program labels are never shell-parsed or executed here.
- `validate/contracts.py:249` binds operation, principal, old/new publications,
  complete task, source commit, budget/model/tokenizer/renderer, execution
  profile/runner and all artifact bytes into a domain-separated subject.
  `validate/approvals.py:87` revalidates the approval envelope and checks issuer,
  domain, operation, subject, time interval and HMAC. Trusted issuance at `:132`
  canonicalizes UTC times; the synthetic marker is authenticated. No request
  field supplies the trusted configured key.
- Approval verification is correctly reusable. There is no misleading fresh
  in-memory replay set. Transactional operation consumption, revocation and
  idempotency remain assigned to the later durable owner as the accepted ADR
  and Task 1 clarification require.
- Core models, all schemas, frozen files and dependency declarations/lock are
  unchanged between BASE and the technical target (independent diff exit 0).
  The identity-extension and legacy-publication assertions are actual tests;
  the implementation's cumulative baseline run is supporting reported evidence,
  not this reviewer's independent M4 execution claim.

## Code quality review

PASS for this task, with no actionable findings (no P0–P3 comments).

Correctness and security checks are concentrated at explicit service boundaries.
The models distinguish transport values from credentials, and the code avoids
shell execution, dynamic command inference, global mutable replay state and
new dependencies. The helpers are small and single-purpose; approval authority,
artifact resolution and semantic binding are separate modules. The two byte
hash checks serve distinct trust boundaries rather than redundant cosmetic
assertions: the resolver snapshots package bytes and the contract boundary
verifies any configured resolver's supplied set against the signed contract.
Linear scans/hashing scale with the supplied artifact set; no unnecessary
database query per artifact or nested candidate search was introduced.

The fixture does call existing private authoring/attestation helpers, but does
so to produce real loader receipts, provenance permits and Registry publications;
it does not forge nominal proof objects. Synthetic programs are correctly
labeled and are not presented as executed behavior or human gold truth.

## Independent verification

Named unresolved doubts from reading the tests were: low/critical task risk
combined with low contract risk; semantic expectation combinations not directly
covered by the implementer's parametrization; exact approval start/end behavior;
and rejection under another configured key or a changed synthetic marker.

Added only the outside-repository diagnostic file
`/private/tmp/cc-m5-task1-review.NZXSdZ/test_review_diagnostics.py`, with real
M5Fixture publications using temporary paths. Executed:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH='/Users/litmus/Documents/Contract Capsule/.worktrees/m5-validation-swap:/Users/litmus/Documents/Contract Capsule/.worktrees/m5-validation-swap/src' .venv/bin/python -B -m pytest /private/tmp/cc-m5-task1-review.NZXSdZ/test_review_diagnostics.py -q -p no:cacheprovider --basetemp=/private/tmp/cc-m5-task1-review.NZXSdZ/pytest-data
```

Actual result: exit 0, `10 passed in 1.62s`.

- Low task/low contract accepts one pair and rejects three; critical task/low
  contract accepts three and rejects one.
- False protected old invariant, true new spillover, false new target, no
  distinguishing old target, and null static expectation all reject after
  genuine publication.
- Approval is accepted at issue time and one microsecond before expiry, rejected
  just before issue and exactly at expiry; another authority key and a copied
  changed synthetic flag reject.

Also independently checked exact diff identity, protected-file equality,
whitespace (`git diff --check`, exit 0), frozen hashes and final tree status.
No repository file was written by this reviewer; Python bytecode and pytest
cache were disabled. All writable diagnostic fixtures live under the temporary
directory. No Docker/candidate code, full suite, lint or type run was repeated.
The handoff's 46 focused/809 cumulative tests, lint/type/lock runs and two
mutation results remain explicitly **implementer-reported** evidence.

## Downstream boundaries, not Task 1 defects

The caller must compose the returned transport with fresh validation and a
verified approval; parsing alone is not execution permission. Later tasks must
materialize the captured bytes into controller-owned staging, mount only each
declared subset, retain separate subject/checker channels, attest observations,
and bind full views/dependencies/current authorization before execution and
activation. A declared helper allowlist cannot statically prove arbitrary
Python programs have no undeclared runtime imports; runtime confinement must
enforce that as planned. Generic activation-subject hashing is not a receipt or
a generation check. Approval keys must stay in the trusted host composition.

This review supports C1/C2/C5 engineering and prospective RQ3 preparation. It
provides no C3/C4 experiment evidence or statistical safety guarantee. No later
M5 task implementation was reviewed or certified; M6 remains unstarted.
