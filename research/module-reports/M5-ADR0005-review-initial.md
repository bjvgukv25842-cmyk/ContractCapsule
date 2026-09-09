# Independent M5 Pre-Implementation Document Review

Verdict: **REQUEST CHANGES**. The proposal is not yet ready for exact-text
author approval. This is a document/design review, not an implementation audit
or an assertion that any M5 behavior has been built or tested.

- Review date: 2026-09-09.
- Reviewed commit: `198616e57fe8b2a2ca701c97701086ebe3a546aa`.
- Base commit: `3bcdbc638de4c10e30fc7dee666e2517450bf1f5`.
- Independent archive: `/private/tmp/contractcapsule-m5-adr-review.iU3JIg`.
- ADR path: `docs/adr/0005-m5-executable-contracts-and-swap.md`.
- Plan path: `docs/superpowers/plans/2026-09-09-m5-validation-swap-execution-plan.md`.
- All line references below refer to those files at the reviewed commit.

## Required Changes

### M5-ADR-R1 [P1]: Make High-Risk Activation Approval Unconditional

Primary anchor: ADR line 274; related ADR lines 119-123, 199-203 and 240-242;
plan line 170.

The proposal correctly separates execution-subject and activation-subject
approvals, but makes activation approval conditional on an unspecified "when
required" and says high risk "also obeys approval_required". The existing
`ActivationPolicy` permits `risk="high"` with `approval_required=false`
(`src/contractcapsule/models/core.py:300`). Effective high risk caused by the
task therefore forces three pairs but is not explicitly guaranteed to force
an activation approval. An implementation using only the boolean flag can
activate a high-risk replacement with an execution-only approval. That is not
the high-risk replacement approval required by CCS-2.1 section 18.1, line 709.

Minimum clarification: define activation approval as mandatory whenever
`effective_risk in {high, critical} OR activation.approval_required`. An
execution-subject approval never satisfies that gate. Bind the activation
subject to the exact prepared replacement/scope and enforce current validity
and revocation in the commit transaction. Preserve separate irreversible-action
control obligations. Add explicit tests for high task risk with low contract
risk/false flag, high contract risk/false flag, and an execution-only approval.

### M5-ADR-R2 [P1]: Define Preconditions Before the Executor Runs

Primary anchor: ADR lines 82-83; related ADR lines 139-150 and 156-163;
plan lines 92-101 and 120-124.

Precondition/static/behavioral/differential results are said to "gate
execution", but the only described checking stage runs after the executor
terminates and receives its output snapshot. Preconditions do not specify
whether they inspect the initial source state or the executor's result. A
repository whose initial tests fail could be repaired by the executor before
the precondition is observed, yielding a passing report for a precondition
that never held at action start. Conversely, requiring postconditions and
differential outcomes before the executor runs creates a circular dependency.

Minimum clarification: prescribe the stages and their exact inputs. Execute
precondition checks on the verified initial source snapshot, before either
subject executor starts, after the execution-approval gate. A failed or
malformed precondition prevents that executor from starting. Place result
checks after subject termination, and relational checks after both members of
the pair exist. Specify whether static verification is an initial-source or
final-state check, or explicitly requires both. Replace the collective "gate
execution" wording with the appropriate stage-specific gates. Bind the stage
and snapshot digest into each authoritative check record. Add a regression
where an executor could fix a failed precondition, proving it is never started.

### M5-ADR-R3 [P1]: Isolate Untrusted Probes from the Checker, Not Just Its Interpreter

Primary anchor: ADR lines 143-145; related ADR lines 106-110, 133-136 and
178-188; plan lines 115-124.

The proposal forbids importing submitted code into the trusted evaluator, but
permits behavioral probes in separate "processes/containers". A separate
process in the same container under the specified 65534 UID is not an
equivalent trust boundary: it can still have readable checker/helper mounts
and inherited checker result descriptors. This leaves the operational claim
that checker artifacts and verdict authority remain outside the subject's
reach unspecified. Hashing an entire artifact set establishes identity, not
which subset each stage is allowed to see. Existing `TestsIntegrity` provides
path/digest/kind bindings, not an executor-versus-checker access partition.

Minimum clarification for the selected Docker profile: execute every untrusted
behavioral subject probe in its own restricted container. Its mounts and
captured output channel must be separate from the trusted checker and must not
expose checker programs, checker-only helpers/expected data, another run, or
the checker verdict channel. Declare closed per-stage artifact subsets; never
mount the whole mixed tests/executor package merely because it was rehashed.
Use self-contained entry points or explicit locked helper subsets; reject
unsupported helper requirements instead of broadening mounts. The checker
alone produces the strict verdict observation; subject stdout remains data.
Add sentinel-read and inherited-result-channel abuse tests, not only attempted
cross-run writes. No additional product or dependency is required.

### M5-ADR-R4 [P2]: Name the Differential Operands and Pair-Level Result

Primary anchor: ADR lines 165-169; related ADR lines 62-83 and 139-150;
plan lines 98-101.

"Compare complete output snapshots" does not identify whether scope checks
compare initial source to each final state, old final state to new final
state, or both. These differ materially: identical out-of-scope edits in both
runs disappear from an old-versus-new diff, while initial-source comparisons
still see them. A sparse output directory also cannot distinguish an unchanged
source file from a deleted one without a specified reconstruction rule.
Separately, a `differential` binding is assigned per-state true expectations,
but no input/result rule explains how a relational checker receives both
states and emits an authenticated pair-level observation.

Minimum clarification: name the verified initial complete repository snapshot
`S0` and the complete final repository states `S_old[i]` and `S_new[i]`; define
exactly which deltas enforce allowed/forbidden scope. State explicitly whether
identical out-of-scope changes in both runs are rejected and why; the author
must approve that interpretation rather than leaving it to implementation.
Keep controller files outside these subject trees, and do not silently exclude
subject-created files. Define differential checks as a post-pair operation
bound to both run/snapshot IDs and the repetition, with an explicit single
pair-level result rule rather than fabricated independent old/new passes.
Add cases for identical outside-scope edits, deletion, untracked creation,
mode-only change and swapped pair operands.

## Alignment and Nonblocking Boundaries

The proposal otherwise explicitly preserves the seven core modules, the nine
existing schema bytes and immutable publications; signed extension identity
avoids a self-referential new-capsule digest. Exact old/new references and
explicit old target expectations are compatible with the bounded replacement
model. M4 whole-provider closure is retained while root replacement-interface
compatibility is not supplied by an unrelated dependency.

Execution permission is distinct from publication, caller-constructed result
objects are not credentials, observations are snapshotted after termination,
and TER/PIP/BSR are separate. Independent view validation covers full inputs,
membership, rendering, evidence and costs rather than compiler flags alone.
Current permission/freshness is distinguished from locked reconstruction time.

The proposed local transactional owner, action epochs, IDLE/RUNNING/UNCERTAIN
states, generation comparisons, atomic pointer/receipt/audit commit,
idempotency, and guarded rollback are coherent at this document-review level.
The limitation to coordinated local policy updates appropriately avoids a
distributed atomic-permission claim. Resource ceilings and unknown-container
fail-closed behavior are stated; their enforcement remains an implementation
and real-Docker test obligation. No further blocking issue was established in
these areas in this bounded review.

The original M5 deadline was 2026-08-24; the current date is 2026-09-09. The
derived plan acknowledges the missed G1/G2/G3 dates and does not use M5 startup
to waive them or begin M6/formal experiments.

## Evidence and Limitations

Independently completed read-only checks:

- Read project AGENTS.md and both complete frozen files; verified both hashes
  in the repository and the exact-commit physical archive.
- Read accepted ADR-0004, complete M1 formal model/failure semantics, latest
  decision-log entries, both proposed documents, production core models,
  canonical identity/package loader, relevant Registry publication/read and
  attestation interfaces, M4 runtime models, compiler/service/validation
  interfaces, renderer, scope and authorization/freshness snapshot types.
- `git archive 198616e57fe8b2a2ca701c97701086ebe3a546aa` completed successfully.
- Exact base-to-candidate diff contains only the two proposed documents:
  305 ADR lines plus 214 plan lines. `git diff --check` exited 0.
- Frozen spec SHA-256:
  `aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c`.
- Frozen execution-plan SHA-256:
  `7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0`.
- Reviewed ADR SHA-256:
  `7c629badd0c214c6cfdf0e54d38c119eae805ed88c383260fd10dcf147d48a21`.
- Reviewed derived plan SHA-256:
  `ee6f60b419a86d6bb48159f1a7e11513dd41abc69411d8624c7e748c39299c06`.

No test suite or Docker process was run by this reviewer. The controller's
reported 763-test baseline and Docker preflight are not represented as this
reviewer's independent results. No repository source, tests, schemas,
governance, index or branch were modified by this reviewer; the only authored
file is this report outside the repository. Concurrent controller governance
edits were observed and left untouched. No subagents were spawned.

Revise these four proposal areas, review the resulting exact text, and then
seek the author's separate ADR approval. This review grants no implementation,
M5 exit, M6, experiment or schedule authorization.
