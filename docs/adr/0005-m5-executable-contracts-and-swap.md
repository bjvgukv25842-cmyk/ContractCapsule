# ADR-0005: Executable Contract Bindings and Local Atomic Replacement

## Status and Authority

**PROPOSED, not author-approved.** Date: 2026-09-09. Module: M5.

The author approved M4 exit and M5 startup, selected signed-core extensions and
Docker isolation, and requested execution of the M5 plan. The plan explicitly
reserves a separate review and author approval for this ADR's concrete text.
Do not implement its new semantic profile before that approval.

Normative inputs are the complete CCS-2.1 and frozen execution plan, with
unchanged SHA-256 values respectively:

- `aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c`.
- `7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0`.

This proposes an implementation profile, not a replacement specification.
M1 definitions/cases, accepted ADR-0004, all nine existing schemas and published
capsules remain unchanged. A conflict with a frozen invariant requires a new
author decision/versioned baseline, not a convenient reinterpretation here.

## Context

M4 compiles and validates its own runtime output but provides no independent
validator, actual behavioral-run evidence, action lifecycle or active pointer.
The production ReplacementContract contains textual clauses and command
strings. M1 has an explicit accepts_interfaces set and boolean reference
outcomes; the production model has neither executable clause bindings nor a
trusted result channel. Shell execution of these strings or caller-authored
passed flags would not operationalize verifiable replacement.

The existing extension map is included in canonical capsule identity. Registry
publication verifies M3 provenance but does not grant arbitrary code-execution
authority. TestsIntegrity locks artifact paths/digests, whereas Registry does
not store the test-program bytes. M5 must resolve those bytes separately and
cannot infer that a test is available from metadata alone.

## Decision 1: Versioned Signed Execution Binding

New replacement candidates use
`ReplacementContract.extensions["x-m5-execution"]`, profile
`ccs-m5-execution/1.0.0`. Parse it with strict immutable models and reject
unknown fields, unsupported profiles, incomplete mappings and ambiguous IDs.
The extension has these required fields:

| Field | Meaning |
|---|---|
| profile | Exact supported execution-profile name |
| replaces_ref | Old capsule ID, exact release version and digest |
| accepts_interfaces | Explicit unique old interfaces accepted by the new contract |
| checks | Ordered CheckBinding records covering all required clauses/commands |
| executor | Locked reference-executor test ID, explicit artifact subset and fixed argument array |
| runner | Image content ID/digest, platform, profile version and resource/output limits |
| repetitions | Exact paired repeat count for the declared effective risk |

No new capsule includes its own final digest in its extension: that would be
self-referential. The external post-publication approval binds the final new
digest. `replaces` must equal the old `capsule_id@version`, `replaces_ref` must
match Registry, and `rollback.pointer` must name the same old version.

A CheckBinding contains check_id, role, phase, clause_path, clause_sha256,
test_id, artifact_ids, argv and subject_probes, plus phase-specific expectations. role is
precondition, static, behavioral, target, invariant, spillover or differential.
phase is pre, post or pair. Pre/post bindings require old_expected and
new_expected booleans and forbid pair_expected; pair bindings require only
pair_expected=true and forbid old_expected/new_expected. clause_path selects an exact existing
array entry: preconditions/i, target_effects/i, protected_invariants/i,
forbidden_spillover/i, or verification/{static,behavioral,differential}/i.
clause_sha256 hashes that entry's exact UTF-8 text, without normalization.

subject_probes is an explicit ordered array (possibly empty) of probe_id,
test_id, artifact_ids, argv and input_state. input_state is initial/current
for pre/post checks and initial/old_final/new_final for pair checks; current
means S0 before execution and the corresponding final tree afterward. The host
runs only these declared probes before their checker, binds each observation
to the probe and snapshot, and supplies read-only observations to that checker.
Checkers cannot request arbitrary new commands or mounts at runtime.

Every core clause and listed verification command must have exactly one binding;
there are no silent skips or extra unmapped checks. check_id and clause_path
are unique. Shared program bytes may serve distinct bindings with separately
locked arguments; each binding still has one independently observed result.
The static/behavioral/differential command strings remain provenance labels,
not shell programs. Their bindings point to TestsIntegrity test_id values with
matching appropriate kind/path/digest. Test IDs must resolve uniquely.

Role matches the selected collection: preconditions use precondition, the
three verification collections use static/behavioral/differential respectively,
and effect/invariant/spillover collections use target/invariant/spillover.
Static and precondition programs reference static TestDefinitions; all other
roles and the reference executor reference behavioral TestDefinitions.
Precondition is phase pre; static/behavioral/target/invariant/spillover are
phase post; differential is phase pair. Precondition/static/behavioral guards
require true in both states; differential has one true paired expectation.
Preconditions gate executor startup; post/pair checks gate preparation and
activation. Guard roles never enter TER/PIP/BSR denominators.

Target, invariant and spillover collections are nonempty for automatic M5
replacement. A legacy capsule lacking this profile or an executable check set
remains usable by M4 but is not an M5 automatic replacement candidate.
Adding/changing binding semantics requires a new immutable capsule version;
behavior-contract changes follow the frozen MAJOR rule, not in-place edits.

Exact interface rules preserve M1: old.provides must be a subset of the new
accepts_interfaces, the new root must provide the task's required interfaces,
and M4 must also validate the full new dependency/view collection. An unrelated
dependency's provides cannot substitute for the new root's replacement
interface. Cross-ID replacement is permitted only by the explicit old ref;
there is no name/version heuristic or relevance-based replacement choice.

## Decision 2: Execution Authority Is Separate from Publication

The controller accepts test bytes only from an explicitly configured local
artifact resolver. For a candidate, load its authorized package through the
existing loader, compare exact Registry projection/signature and rehash every
TestsIntegrity artifact. Missing bytes block. Do not fetch a path from a
capsule string or trust a mutable working directory after validation.

Materialize verified bytes in controller-owned staging; the identity lock
covers the whole supplied test/executor artifact set and image, including
transitive helper files. M5's reference entry point is pinned Python `-I` with
an absolute verified program path and an argv array. No shell, shell splitting,
runtime pip installation, user environment inheritance or implicit PYTHONPATH.

Before running ANY candidate program, require a valid ExecutionApproval issued
by the configured trusted approval authority for the requesting principal and
exact old/new capsule refs, source repository commit, test/executor digests,
runner config, contract profile and expiry. Publication identity is necessary
but is not that execution permission. The module-start approval is not a
blanket runtime approval. Test approvals must be labeled synthetic.

Use the existing local research trust approach (standard-library HMAC-SHA256),
with separate domain-separated execution/activation subjects and a configured
authority key not supplied by the request. Keep approval authority separate
from run-result attestation authority; neither key enters a container or an
artifact export. No production PKI/interoperability claim is made.

The host runner, not the task process, assigns run/attempt IDs and binds
container identity, input/view/contract/test/config digests, role and repetition
to captured outputs. AgentRun/check/report dataclasses are transport values,
not credentials. Publicly constructed or edited results cannot replace the
runner's authoritative, append-only, authenticated stored records.

## Decision 3: Trusted Observations and Separate Behavioral Components

Run the same reference executor from the same clean repository commit in old
and new environments, changing only the supplied compiled view. The task
executor cannot receive old/new labels, expected outcomes, protected checker
programs, approval credentials or another run's outputs. This ensures the
fixture demonstrates a context-caused change, not a label-conditioned mock.

Use these stages for repetition i, with snapshot digests authenticated by the
host runner. S0 is the complete verified initial repository tree at the locked
commit, not an output directory or a Git-status filtered subset.

1. Verify execution approval, artifacts and old/new views; create identical
   complete writable subject copies of S0. Before EITHER executor starts, run
   both states' precondition checks against S0 and their locked view. Any failed,
   missing or malformed precondition prevents both executors from starting.
2. Run each subject executor in its own restricted container. Preconditions
   cannot be repaired by a task that should never have started.
3. After verified termination of all writers, snapshot each COMPLETE resulting
   subject tree as S_old[i] and S_new[i]. A missing source file is a deletion,
   not an unspecified unchanged file. Run static and other post checks against
   S0 plus the corresponding final state and its view. Static here means
   final-state verification; initial-source tests must be bound as preconditions.
4. Once both sides and their valid post records exist, run each differential
   check once on (S0,S_old[i],S_new[i]). Its one paired observation binds both
   run IDs, both final snapshot digests, S0 digest and repetition. Compare it
   to pair_expected=true; never fabricate two per-state differential passes.

Trusted checker containers must not import/eval submitted repository code into
their interpreter or accept task stdout as a passed-check record. EVERY
untrusted behavioral subject probe runs in a separate restricted container,
not merely a sibling process under the checker's UID. The host orchestrates
probe execution and passes captured observations to the trusted checker.
Probe stdout/exit is data; only the checker owns its observation/result channel.

Each executor/check binding names a closed, digest-locked artifact_ids subset
of TestsIntegrity, containing its entry point and every helper. Required probe
programs use an explicitly locked subject-only subset; undeclared imports or
helper needs block rather than broadening a mount. Executor/subject subsets
are disjoint from checker-only programs/helpers/expected-data artifacts; sharing
a mixed executor/checker entry point is rejected. Never mount the entire mixed
TestsIntegrity package as a convenience.

Per-stage visible mounts: executor gets only its program subset, safe task
input, its view and its writable S0 copy; subject probes get only their subset
and designated subject snapshot/observation inputs. Neither receives checker
artifacts, another run, expected outcomes, credentials or a checker output FD.
Pre checkers get their checker subset plus read-only S0/view; post checkers get
that subset and read-only S0/final-state/view; pair checkers get their subset
and read-only S0/old/new states. All checker result streams are separate host
captures bound to their exact trusted container ID/phase, not inherited subject
descriptors. Controller logs/keys/tickets live outside subject trees entirely.

Each checker emits exactly one strict JSON observation with its expected
check_id and a boolean observation; duplicates, extra IDs, missing/malformed
output, abnormal exit, skip, timeout or output limit failure block. The host
compares this observation to the signed phase-appropriate expectation. Each
authoritative record includes phase and exact input snapshot digests.
False target observation is a valid unfavorable outcome, not a crash to retry.

For target checks, new_expected is true; for invariants both expectations are
true; for spillover both are false (the observation means forbidden behavior
triggered). Old target expectation is explicit rather than assuming the old
version already meets the new goal. Every paired old state must match its own
declared expectations and preconditions. At least one target must distinguish
old false from new true for the reference behavior-changing replacement.

Report target successes/count as TER, invariant successes/count as PIP and
triggered spillover/count as BSR, with individual check records. Activation
requires TER=1, PIP=1, BSR=0, complete precondition/static/differential checks,
and stable repetitions. No combined score can compensate for a failed check.

Independently compute all three full-tree deltas: S0->S_old[i], S0->S_new[i]
and S_old[i]->S_new[i]. BOTH S0-relative deltas enforce allowed/forbidden scope;
identical out-of-scope edits in both runs therefore still block even if the
old/new delta is empty. The old/new delta is retained for relational checks
and reporting, not used as a substitute for source-relative scope enforcement.
Compare path entry types, additions, deletions, contents and permission modes,
including subject-created/untracked files and directory-mode changes. Do not
silently exclude subject artifacts. Reject incomplete snapshots and unsupported
file types; keep host bookkeeping outside them. Reuse M4's anchored POSIX glob
semantics: any changed path outside allowed scope or inside forbidden scope
blocks; an empty allowed scope permits no change. These checks supplement,
not replace, behavioral BSR. Author approval of this ADR accepts this explicit
conservative interpretation rather than leaving differential operands implicit.

## Decision 4: Locked Docker Research Profile

Use an explicitly locked local image and platform, never a moving tag during a
run. No pull or network fallback. Initial inspected Linux/arm64 reference image:
`sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203`.
Runtime/CI must preflight the exact image and platform; a missing image blocks.

Profile `ccs-m5-docker/1.0.0`: non-root65534:65534, network none, read-only root,
all capabilities dropped, no-new-privileges, no privileged/host PID/host network
mode, no Docker socket or credentials mounted. Use only fresh controller-owned
snapshot/output directories with fixed container mount destinations. Reject
user-directed mount paths, device nodes, FIFOs, unsafe links and Git submodules
in this initial reference profile; do not silently omit unsupported entries.

Default signed limits:1CPU,1GiB memory with no extra swap,128processes,
300seconds per execution/check stage,4MiB each stdout/stderr,64MiB aggregate
output tree and10000files. Limits are enforced by the host runner as well as
Docker where applicable; output excess is a failure, not a truncated success.
Lower limits may be locked consistently; raising a profile ceiling requires
explicit review and a new approved runner configuration. Old/new limits match.

On timeout/output excess, stop the exact owned container, verify it is stopped,
capture failure metadata, and retain the attempt. Do not remove arbitrary
containers/volumes or clean user paths. Container daemon failure is fail-closed;
unknown live processes leave an uncertain action state, not a timed-out safe
boundary. Docker is an isolation control, not a proof against kernel/daemon or
privileged-host compromise.

Effective risk is the maximum of task and activation-policy risk. Run one pair
for low/medium and three predeclared pairs for high/critical. All required pairs
must pass; any mixed valid outcomes yield UNSTABLE_TWIN_RUN and block. Additional
repetitions, if separately authorized, retain every earlier outcome. These are
deterministic engineering fixtures, not formal statistical safety thresholds.

## Decision 5: Independent Runtime Validation

Bind validation to full CompileRequest, exact old/new root and dependency sets,
view bytes/manifest/handles, principal, source commit, test set and service
configuration. Revalidate Registry identities and actual source bytes.
Recompute P0 membership, required provider/atom closure, conflicts, exact
rendering/handles and full-text token cost independently of compiler flags.
Recompilation may compare deterministic selection, but matching the compiler
to itself is never the sole proof of view validity.

Reconstruction uses the original locked compile time. Current authorization,
validity and source freshness use an injected current UTC clock immediately
before execution and activation. Old as_of and successful cached reports cannot
extend permission. Any loss of a required member blocks; M4-R3's safe public
failure projection must be preserved. Redacted token zero is not a measurement.

## Decision 6: Durable Local State and Safe Boundaries

Add separate m5_* runtime tables in the existing local Registry SQLite database;
never update immutable publications/evidence/core records to mark ACTIVE.
An additive schema migration must leave old records byte-identical and all
existing APIs usable. Runtime state is C-zone, excluded from core identity.

Scope active state by tenant, principal, repository, environment and session.
An ActiveBinding contains root CapsuleRef plus the full view/input lock and a
monotonic generation. Initialization is an explicitly authorized, validated
bootstrap of an empty session's old binding, never an update escape hatch.

Action states are IDLE, RUNNING and UNCERTAIN. begin_action and safe-boundary
reservation are serialized in the same transactional state owner. A boundary
ticket binds scope, expected generation, action epoch, operation and expiry;
only the controller can issue/consume it. Expiry never proves an action ended.
RUNNING/UNCERTAIN sessions cannot activate or roll back; recovery needs trusted
process/container termination evidence and an explicit reconciliation event.

PreparedReplacement records bind old/new ActiveBinding, request/principal,
validated current views, reports, run IDs, execution approval, activation
approval under the predicate below and expiry. Expensive Docker/check work happens outside
the commit transaction. activate(candidate,boundary) uses a session-scoped
controller with an explicit prepared-record ID bound by composition; the
candidate ref alone cannot choose the latest convenient report.

Use BEGIN IMMEDIATE and compare expected generation plus exact old binding.
Within the transaction reverify stored attestations, approved subject hashes,
current permission/freshness, action state and ticket. Record pointer change,
ticket consumption, receipt and critical audit event in one commit. A failed
commit changes none; an unrecordable critical event cannot be downgraded to
optional telemetry. Optional external log export may lag behind durable data.

Local approval revocations and action/pointer changes use this transactional
owner. The supported authorization integration supplies immutable snapshots
and serializes supported policy updates through the same owner; an external
mutable policy service without that coordination is not an atomicity promise.
Rechecks alone must not be described as distributed atomic permission control.

Idempotency binds operation ID and full request digest. Identical retries find
the prior durable outcome; the same ID with different input is rejected.
Each receipt is authenticated/stored by the controller; nominal receipt copies
are revalidated. Crash after commit/before reply returns that committed receipt
on retry, not a second activation. No automatic retry replaces valid failures.

Rollback validates the original applied receipt, current authorization and old
view evidence at a safe boundary. It compares current generation/new binding
to the receipt before restoring the old binding with a new generation. A stale,
foreign, forged or never-applied receipt cannot overwrite subsequent state.
Repeat the same rollback operation idempotently; do not apply it twice.

ActivationApproval is mandatory iff effective_risk is high/critical OR
activation.approval_required is true. Task-high/contract-low and high/false-flag
cases cannot bypass it. ExecutionApproval is a different subject and never
satisfies activation approval. Bind the activation subject to the exact
prepared evidence/request/scope and expected old generation, excluding the
approval's own envelope to avoid self-reference. Recheck its validity, expiry
and revocation inside the commit transaction.

Context rollback restores only future context. Irreversible-action controls
separately require bound trusted preflight, approval or a compensation plan;
they do not waive the high-risk ActivationApproval predicate. The M5 fixture performs no actual email, payment,
deployment or irreversible deletion, and never claims external-effect rollback.

## Alternatives and Consequences

- A signed external execution plan was considered but not selected by the
  author; embedding bindings avoids an extra facts-versus-plan identity owner.
- Executing command strings or trusting user-supplied reports is rejected.
- Host-only worktrees were considered but the author chose Docker isolation.
- Separate mutable runtime tables preserve core identity; mutating published
  lifecycle fields or using an unversioned file pointer is rejected.
- Strict checks, complete payloads and repeated runs can increase cost/blocking.
  Report this cost; do not weaken RQ3, conceal failed attempts or expand M5
  into adapters, benchmark construction, UI or production infrastructure.

## Acceptance and Author Gate

Before M5 exit, prove executable binding integrity and authorization separation;
old/new observation isolation; TER/PIP/BSR separation; independent view tamper
rejection; all unsafe fixtures preserve the actual old pointer; every safe
fixture activates and rolls back without changing immutable cores; concurrent,
replayed, expired and crash-recovery requests cannot cause partial updates.
Include mutation tests for each boundary, not merely happy-path unit tests.

All763 baseline tests and the frozen M5 integration/security commands must pass,
followed by full lint/type/complexity/scanner-inventory/lock/schema/hash checks
and an independent read-only implementation audit. Report engineering evidence
for C1/C2/C5 and prospective RQ3, not formal benchmark results.

This ADR needs independent document review and explicit author approval of its
exact committed text before M5 semantic implementation. Neither document review
nor module startup approves M5 exit, M6, a revised schedule or formal experiments.
