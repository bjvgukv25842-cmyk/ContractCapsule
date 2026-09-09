# M5 Validation and Atomic Replacement Execution Plan

> Required execution skill: superpowers:executing-plans. Use real failing tests,
> small commits and independent read-only reviews. Stop at every author gate.

Goal: implement the mechanism needed to test verifiable context replacement,
not an adapter product or empirical superiority claim.

Architecture: preserve M2/M3 immutable Registry/evidence and the approved M4
compiler. Add strict signed execution bindings, independent validation, trusted
Docker-run observations, separately evaluated behavior, and transactional C-zone
action/pointer/receipt state. Public dataclasses are never trust credentials.

Stack: existing locked Python3.12/Pydantic/SQLite/JCS/pytest/Hypothesis services,
standard-library subprocess/HMAC and the local Docker CLI. No new dependency
is authorized or needed for this preparation phase.

Inputs: complete CCS-2.1 and frozen execution plan, accepted ADR-0004, M1 formal
and failure semantics, latest decisions, M4 technicalbb1d56d/governance1aeeb11,
and proposed ADR-0005. This derived plan does not amend frozen files.

## Current Gate and Preflight

- [x] Record the author's M4 exit approval and M5 startup authorization.
- [x] Branch codex/m5-validation-swap from approval commit
  `3bcdbc638de4c10e30fc7dee666e2517450bf1f5` into its isolated worktree.
- [x] Verify both frozen hashes; retain all nine schema bytes and763 old tests.
- [x] Prepare the existing environment using uv sync --locked --offline.
- [x] Recheck Docker engine/local image and a bounded no-network container.
- [ ] Independent document review of the exact proposed ADR/plan.
- [ ] Author approval of ADR-0005's exact reviewed commit and digest.

Before ADR approval, only governance, preflight and proposal documents may be
created. No x-m5 parser, runtime table, validator, execution authority, runner
or fake implementation shell is added. A test count from M4 is not M5 progress.

## M5-1: Executable Contract and Authority Bindings

After ADR approval, create strict runtime types in validate/models.py and
validate/contracts.py, with service protocols in validate/protocols.py.
Keep production core models and all existing schemas unchanged. Expose a strict
parse/validate operation for x-m5-execution rather than altering M2 acceptance.

- [ ] Write tests/unit/test_execution_contract.py against real approved capsule
  fixtures for wrong clause hash/index/role, duplicate IDs, missing mappings,
  wrong artifact kind/hash, ambiguous test ID, missing bytes, incompatible old
  interfaces, wrong old ref and absent execution approval; observe actual RED.
- [ ] Implement profile parsing, exact old ref/interface compatibility, complete
  check mapping and local artifact resolution as specified in ADR-0005.
- [ ] Add post-publication execution approvals with separate trusted issuance,
  domain-separated subjects, expiry and replay/binding checks. Candidate code
  must not receive any approval/attestation key.
- [ ] Show extension changes alter new capsule identity while old published
  versions and ordinary M4 legacy views remain unchanged; test reciprocal
  TestsIntegrity/checksum references using the real loader and Registry.
- [ ] Run focused and accumulated tests; independently review and commit.

Produces immutable ReplacementRequest, executable profile/check bindings and
verified execution-approval records for all subsequent tasks. Do not infer a
target or invocation from natural-language strings.

## M5-2: Independent Integrity, Evidence and Compression Validation

Create validate/integrity.py, evidence.py and compression.py. Explicitly inject
Registry, current authorization/freshness, artifact resolver, token counter,
neutral renderer and clock through a request-scoped validation service.
Preserve the frozen validate_integrity(capsule), validate_evidence(capsule) and
validate_compression(view,capsules) shapes as methods on that composition.

- [ ] Write tests/unit/test_m5_validation.py that clear compiler blockers,
  remove P0/provider/dependency members, swap handles, alter rendered bytes,
  forge public models, reuse reports across principals/tasks and advance time
  past validity. Assertions must check invalid reports and no activation proof.
- [ ] Independently recompute mandatory membership, closure/conflicts, exact
  rendered content/handles and complete text cost from verified cores. Compiler
  replay comparisons are additional evidence, not the only validator.
- [ ] Separate reconstruction as_of from current authorization/freshness time;
  keep current failure privacy and the meaning of withheld token data intact.
- [ ] Bind reports to request, capsule/input set, full view fingerprint, tests,
  principal and service configuration; store authenticated authoritative records.
- [ ] Fault-inject validation bypasses, run cumulative tests, review and commit.

Produces IntegrityReport, EvidenceReport and CompressionReport; none is accepted
by downstream services merely because the caller constructed a valid model.

## M5-3: Behavioral and Differential Evaluator

Create validate/behavior.py. Preserve evaluate_contract(run,contract) and
compare_runs(old,new,contract). Consume only verified authoritative run/check
records bound to the exact approved execution profile.

- [ ] Write tests/unit/test_behavior_contract.py proving that a target failure,
  invariant failure and spillover trigger block separately; include missing,
  duplicate, extra, skipped, timeout and malformed results.
- [ ] Implement per-check observations and explicit old/new expectations;
  report three numerators/denominators independently. Verify old-state setup
  without requiring it to satisfy the new target before replacement.
- [ ] Compare complete output snapshots, including untracked files and modes,
  against allowed/forbidden anchored paths; keep behavioral spillover distinct.
- [ ] Reject mismatched task/source commit/image/test/executor/budget/repetition
  binding; retain every valid unfavorable result and unstable repeat group.
- [ ] Test forged result/receipt inputs and counter mutation, review and commit.

Produces ContractReport and DifferentialReport plus preserved check traces.
No RCS aggregate overrides a failed component; no formal statistical claim.

## M5-4: Real Docker Paired Execution

Create swap/twin_run.py and swap/docker_runner.py. Use the frozen signatures'
AgentRun type for versioned run transport; a reference executor in M5 is not a
Codex/Claude adapter. Exercise a real local repository fixture whose same task
program changes behavior only when supplied a different compiled view.

- [ ] Write tests/integration/test_twin_run.py proving real process execution,
  two isolated snapshots, read-only checker artifacts, exact input/output
  records, and blocked unavailable/mismatched images. Never skip Docker tests
  and then report M5's exit passed when Docker is unavailable.
- [ ] Implement image/platform/profile locking, fixed argv, no pull/network,
  minimum mounts/privileges and resource/output limits. Enforce all ceilings.
- [ ] Stop and verify owned containers before snapshot/checker handoff. Test
  timeout, output floods, process residue, unsafe file types and attempted
  cross-run/checker writes without contacting real external systems.
- [ ] Observe check results through trusted separate workers; do not trust
  task stdout as a verdict or pass expected labels to the task executor.
- [ ] One pair for low/medium, three predeclared pairs for high/critical;
  mixed results block. Run real fixture/mutation tests, review and commit.

Outputs include authoritative run IDs, input/view/artifact digests, container
identity, exit/termination status, check observations, file snapshots and usage
availability metadata. Do not invent provider costs for a reference executor.

## M5-5: Runtime Store and Safe Action Boundary

Create swap/store.py, boundary.py and runtime models; add m5_* runtime tables
through an additive migration in the same local SQLite database. Keep Registry
publication records immutable. Do not expose an unconditional pointer-set API.

- [ ] Write tests/unit/test_swap_store.py and test_safe_boundary.py proving
  empty-session-only initialization, exact scope isolation, generation compare,
  ticket authenticity/expiry/one-time use and RUNNING/UNCERTAIN rejection.
- [ ] Bind initialization to validated old ActiveBinding. Persist action
  epochs, prepared records, operation IDs and scoped current bindings.
- [ ] Serialize begin/end/reconcile actions and boundary reservation; do not
  treat lease expiry or a dead client as evidence the tool stopped.
- [ ] Test two competing connections/processes, uncertain crash recovery,
  identical idempotent requests and conflicting operation-ID reuse.
- [ ] Verify old database contents/API behavior and full regressions; review.

M5 supports coordinated local authorization updates, not arbitrary independent
remote-policy atomicity. The trusted state owner mediates changes relevant to
activation; unsupported concurrency models fail preflight rather than being
described as safe by repeated reads alone.

## M5-6: Atomic Activation, Receipts and Guarded Rollback

Create swap/controller.py. The controller is bound to principal/session/request
and explicit prepared-record ID; preserve activate(candidate,boundary) and
rollback(receipt). CapsuleRef alone cannot choose reports or confer authority.

- [ ] First write tests/integration/test_replacement.py and the exact frozen
  security tests below with assertions on durable pointer state, not only codes.
- [ ] Bind all reports, approvals, old/new roots and dependency/view locks;
  prepare outside the commit transaction and revalidate immediately inside it.
- [ ] Atomically commit pointer generation, ticket consumption, receipt and
  critical audit event. Exercise failures before commit and after commit before
  response; repeat requests return the original durable outcome.
- [ ] Restore only from a valid applied receipt and current matching generation,
  with old evidence/current permissions and a new safe boundary. Stale/foreign
  receipts cannot undo later activations; repeated rollback is idempotent.
- [ ] Require genuine irreversible-action control evidence and any risk approval;
  never execute actual irreversible external effects in the reference fixture.
- [ ] Run behavior/transaction fault injection, full regressions, review, commit.

## M5-7: Integrated Exit and Research Evidence

Required frozen security node names:

```text
test_mid_tool_call_activation_is_rejected
test_irreversible_action_requires_control
test_failed_gate_preserves_active_pointer
```

Required frozen command:

```bash
uv run pytest tests/integration/test_replacement.py tests/security/test_fail_closed.py -v
```

- [ ] Execute one real deterministic old/new reference task through independent
  validation, Docker pairs, evaluation, prepare, activation and rollback.
- [ ] Verify all unsafe cases keep the old active binding, all safe cases can
  activate/rollback, receipts survive restart and immutable cores never change.
- [ ] Run763 original regressions plus new tests, formal fixtures, Ruff/Mypy,
  normal/no-ignore C901/PLR0911/PLR0912/PLR0915 and actual filesystem inventory,
  lock/hash/schema/build/ledger/whitespace checks. No threshold weakening.
- [ ] Independently audit the exact committed candidate in a clean read-only
  environment; retain real failing mutants and original unfavorable records.
- [ ] Record decision log, Claim-Evidence Matrix, AI ledger, module report and
  exact artifact hashes. New blocking findings require itemized repair approval.
- [ ] Stop at the author's M5 exit gate; explicitly state M6 has not started.

## Paper and Schedule Boundary

Primary evidence: C1 replacement relation, C2 mechanism and C5 provenance;
prospective RQ3 operational measurements. No synthetic test is human benchmark
truth, no M5 result establishes C3/C4 or cross-agent superiority, and M5 alone
does not satisfy M6's real-Agent G1 vertical slice.

Estimated implementation/local verification is8-12engineering days, with ADR,
independent review and author waits separate. G1/G2/G3 old dates are missed.
M5 authorization permits continued engineering, not a claim that the frozen
submission calendar is feasible. Any structural schedule/study change requires
separate ADR/author action and cannot sacrifice RQ3 or silently revise baselines.
