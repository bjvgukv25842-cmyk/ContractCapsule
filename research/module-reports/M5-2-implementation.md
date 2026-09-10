# M5-2 implementation handoff

Date2026-09-10. Task2 base31e7b49b2533a1366978ef6c272707c3812ea56d,
with controller-only governance90b8394 arriving before technical commits.
Technical commits:c4fa931 (journal/reports) and917e702 (independent services/tests).
Independent review remains pending; this report is implementation evidence only.

Read complete AGENTS.md, both frozen files, accepted ADR-0005, derived M5 plan,
Task2 brief, Task1 interface report and latest decision-log entries. Used
executing-plans, git-workflow, TDD, verification-before-completion and finishing
instructions. Existing codex/m5-validation-swap worktree preserved. Only Task2
executed; no network, extra dependency, external plugin or subagent was used.

Frozen SHA256s match:
aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c and
7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0.

## Exact integration APIs

```python
from contractcapsule.validate.integrity import ValidationService
from contractcapsule.validate.artifacts import LocalArtifactResolver
from contractcapsule.validate.journal import RecordJournal, RecordVerifier, RecordRef, RecordError
from contractcapsule.validate.reports import IntegrityReport, EvidenceReport, CompressionReport

journal = RecordJournal(registry, journal_hmac_key)  # bytes, at least32bytes
service = ValidationService(
    request,       # actual strict M4 CompileRequest with full input publications
    compiler,      # M4 ViewCompiler composition, supplying explicit Registry,
                   # authorizer, freshness, ranker, counter, native source resolver,
                   # neutral renderer
    artifacts,     # exact LocalArtifactResolver, configured digest -> package Path
    journal,       # must use the SAME Registry object/database
    clock,         # callable -> timezone-aware UTC datetime, no nonzero offset
)
service.validate_integrity(capsule: Capsule) -> IntegrityReport
service.validate_evidence(capsule: Capsule) -> EvidenceReport
service.validate_compression(view: CompiledView, capsules: list[Capsule]) -> CompressionReport
service.verify_report(report, capsules: list[Capsule], *, view: CompiledView | None = None) -> None
# verify_report raises RecordError("record rejected") on any rejection.
```

Capsule arguments are actual capsule values corresponding to request publications.
Compression requires the exact complete input capsule multiset; integrity and
evidence methods validate the single given member. Core/signature/status identity
comes from Registry, never a caller-created PublishedCapsule. Artifacts are read
through the configured Task1 local package loader/snapshot resolver and their
complete test ID/path/kind/digest/actual-byte set is independently rechecked.
Duplicate test IDs/paths and unavailable/mutated artifacts fail. No test executes.

All report models are immutable transport values. Fields:
kind (`integrity`, `evidence`, `compression`), valid, blockers, validated_at,
scope_digest, subject_digest, tokens, record. Only a successful compression
report includes measured TokenAccounting. Valid reports always have real UTC
validation time and exact scope/subject digests. `payload_bytes()` gives JCS
bytes excluding the record reference, avoiding a self-referential digest.

```python
reference = journal.append(kind=kind, scope=scope, subject=subject, payload=bytes)
reader = journal.verifier()
payload = reader.verify(reference, kind=expected_kind,
                        scope=expected_scope, subject=expected_subject)
```

RecordRef has record_id and payload digest. The journal is a trusted-host writer,
not an API handed to subjects. Only the read-only verifier goes to consumers;
neither key goes to Docker. Use a journal key distinct from ApprovalAuthority.
RecordVerifier has no append/sign method. Its local HMAC trust assumes the host
and private Python object state are not compromised, as with Task1.

The additive m5_records table lives in Registry.database_path. Each row stores
record_id, kind, scope, subject, exact payload bytes and HMAC signature. The
signature covers domain, record ID, kind/scope/subject and actual payload SHA256.
Update/delete triggers enforce append-only API semantics. A fresh journal with
the same key reads old records; wrong keys, wrong expected subject/scope/kind,
unknown references, payload tampering and signature tampering fail safely.
RecordVerifier can be constructed from database_path and the host-owned key for
later transaction-owner composition; Task5 may add connection-bound verification
where required for its atomic transaction, without changing publications.

## Independent validation and privacy

Direct checks rebuild admission and the verified graph from Registry cores,
independently call the configured ranker to determine related P1 atoms, require
P0/P1/task IDs/root provider members and mandatory closure, and reject conflicts.
Selection is checked against exact admitted owner/atom pairs, participating
capsules and closure links. Every native evidence result is rehashed and compared
with its exact core record, locator/span, owner, mode, member IDs and resolver
version. Neutral rendering and complete-text token accounting are recomputed.

Manifest metadata/provider/service projection is reconstructed from the verified
graph, admission and request. It reuses M4 build_manifest as a deterministic
wire-format projection, with a newly assembled Compilation state; it does NOT
invoke Compilation.run, _select, _mandatory or _final_checks for the direct
validation. Service stamp serialization is reused. Decision reasons are taken
from the supplied decisions for projection, and checked by the supplemental
compiler replay. P0/P1 membership, closure/conflicts, handles, rendered bytes,
costs, request/permission/services/providers and expected output lock are checked
directly even when the compiler returns its own forged view. Optional ranking
selection/reason correctness additionally uses production compiler replay; this
is not a second full implementation of M4's optional budget-selection algorithm.

Reconstruction uses request.as_of. A separately injected current clock checks
authorization, validity and freshness before validation and again at the end.
The current admitted membership/rejection counts must match reconstruction;
policy/service configuration must remain stable. A clock may advance normally
within the freshness interval; time-dependent snapshot digests are not compared
as if the clock were frozen. Reports include the complete request (including
expected_manifest_digest), source/test locks in core, signature/status, full
view/manifest/handles, actual artifact identities and service/policy configuration.

All expected/unknown operational failures return invalid reports with only safe
generic codes. Failure subjects, scope digests and token counts are withheld,
including current revocation; no atom/capsule identity or exception text leaks.
Invalid reports are persisted as authenticated privacy tombstones under literal
scope/subject `withheld`; these records are never accepted by verify_report.
When the clock itself fails, validated_at is None, not an invented timestamp.
When persistence fails, record is None and blocker REPORT_PERSISTENCE_FAILED;
this is not success or optional telemetry degradation.

verify_report recomputes scope/subject and current admission, validates exact
stored payload bytes, and rereads artifact bytes. It authenticates this report;
it does NOT replay full source/render validation again. Task3-6 consumers must
check the expected report kind and call fresh validation immediately before
execution/activation, then verify stored references. Successful old reports do
not extend permission or source freshness. Coordinated transaction-time policy
control remains Task5/6; no distributed atomic authorization claim is made.

## Actual RED/GREEN and validation evidence

1. Initial collection RED: missing new integrity module, exit2. This is discovery
   only, not behavioral proof. A minimal service shell then exposed an incorrect
   timestamp formatting issue; fixed the shell representation before behavior RED.
2. Real Registry and production M4 pipeline passed; initial independent report
   returned invalid. Positive persisted-report assertion failed (exit1) before
   implementation. After independent core/render/source gates,8tests passed.
3. Added malicious compiler manifest changes and ticking-clock tests:6failed,
   8passed. False success accepted request/permission/task/services/provider
   tampering; final admission compared clock-dependent digests. Fixed direct
   manifest projection and current-membership comparison;14passed.
4. Expanded real-source corruption fixture initially used nonexistent Registry.cas
   and then hit read-only CAS permissions. These were fixture errors, not security
   RED. Corrected to the actual _cas.object_path and explicit local chmod corruption.
   The normal immutable CAS API remains untouched.44tests subsequently passed.
5. New tests exposed duplicate test-ID acceptance and fabricated1970 timestamp
   when the clock failed:2failed/1passed. Fixed both;3focused passed.
6. Added expected manifest lock test with lying compiler:actual1failed; implemented
   direct expected digest check. Raw output preserved in task-2-lock-red.log.
7. Final focused `uv run pytest tests/unit/test_m5_validation.py -q`:exit0,
   48passed12.22s, task-2-focused-green.log.
8. Final cumulative `uv run pytest -q`:exit0,857passed50.59s, full raw output
   task-2-full-green.log. This is809unchanged baseline+48new tests.
9. In-process mutant replacing compression._membership with selected IDs only:
   the two self-consistent P0/P1 omission tests fail (assert not True). Latest raw
   task-2-membership-mutant.log:exit1,2failed0.73s. An earlier diagnostic execution
   of the same mutant also failed; it was repeated only to preserve raw output.
10. In-process HMAC compare_digest bypass:wrong-key test fails DID NOT RAISE,
    exit1,1failed0.59s; raw task-2-journal-mutant.log. Mutants never edited files.
11. `uv run ruff check .`, same with --no-respect-gitignore, and
    `--select C901,PLR0911,PLR0912,PLR0915` under both modes:all exit0.
    `uv run mypy .`:exit0,86files. Ruff show-files inventory87under both modes
    (86Python files+pyproject). Formatting touched only Task2 new files.
12. `uv sync --locked --offline`:exit0,46resolved/45checked. `git diff --exit-code
    31e7b49b2533a1366978ef6c272707c3812ea56d -- schemas pyproject.toml uv.lock
    docs/spec/CCS-2.1.md docs/superpowers/plans/2026-07-30-contract-capsule-fse-2027-execution-plan.md`:
    exit0. Hash recheck matches both frozen baselines. git diff --check and staged
    whitespace checks pass. Only six new Task2 technical/test files committed.

## Boundaries and next step

No behavior evaluator, AgentRun, Docker invocation, activation proof, approval
redemption, pointer state, action lease/ticket, transaction receipt or rollback
exists in this task. Invalid-report assertions cannot claim that a not-yet-built
pointer remained unchanged. Task3-6 must prove those boundaries on actual state.
The present fixtures are synthetic engineering evidence, not human benchmark
truth, observed behavior effects, empirical safety rates or provider token costs.

Independent review should inspect the exact917e702 candidate and six-file scope.
Main owns claim-evidence/decision-log/AI-ledger updates. Supports C1/C2/C5 and
prospective RQ2/RQ3 engineering evidence; no C3/C4/RQ1/RQ4 empirical result.
Original M5Aug22-24schedule is missed; no G1/G2/G3 or schedule waiver.
未开始下一模块（M6）；本子任务未执行M5-3及以后任务。
