# M5-3 implementation handoff

Date2026-09-10. Assigned basef161910952cbbefc367198a373cce21b6fee5a16;
controller governance44b89eb arrived during this task. Technical commit:
20cb819c19c6c4c6edf632ba1d6d21bc0e53fffd. Only four new technical/test files are
owned here: validate/behavior.py, validate/run_models.py,
validate/snapshots.py, tests/unit/test_behavior_contract.py.

Read AGENTS.md, complete frozen CCS-2.1/execution plan, accepted ADR-0005,
derived M5 plan, latest decision log, Task3 brief and exact Task1/2 reports.
Used executing-plans, TDD, Git workflow, verification-before-completion and
finishing-a-development-branch instructions. Existing isolated worktree is
preserved; no merge/push. No subagent, dependency, schema, M1-M4 implementation
or original test was changed. Main owns governance and independent review.

Both frozen SHA256s match:
aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c and
7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0.

## Consumer APIs and authority

```python
from contractcapsule.validate.behavior import BehaviorService, HostRunRecorder
from contractcapsule.validate.run_models import (
    AgentRun, EvaluationContext, RunEvidence, PairEvidence, ProcessCapture,
    CheckCapture, Snapshot, TreeEntry, ContractReport, DifferentialReport,
    RepetitionReport, identity, stage_subject,
)

context = EvaluationContext(
    initial=initial_snapshot,       # complete independently captured locked S0
    old_view_digest=old_view_hash,  # complete verified view+input/manifest lock
    new_view_digest=new_view_hash,
    approval_digest=approval_hash,  # complete verified execution approval envelope
    synthetic=False,               # fixture tests use True, never real execution
)
recorder = HostRunRecorder(bound, context, journal)
service = BehaviorService(bound, context, journal.verifier(), journal)
# bound: Task1 parse_execution_contract result, not arbitrary transport authority.
# journal: same Registry-backed Task2 RecordJournal, configured host-only key.

recorder.record_run(evidence: RunEvidence) -> AgentRun
recorder.record_pair(old: AgentRun, new: AgentRun,
                     evidence: PairEvidence) -> tuple[AgentRun, AgentRun]
service.evaluate_contract(run: AgentRun, contract: ReplacementContract) -> ContractReport
service.compare_runs(old: AgentRun, new: AgentRun,
                     contract: ReplacementContract) -> DifferentialReport
service.evaluate_repetitions(pairs: tuple[DifferentialReport, ...]) -> RepetitionReport
service.verify_report(report: ContractReport | DifferentialReport | RepetitionReport) -> None
# verify_report raises safe RecordError("record rejected").
```

These are request-scoped service methods preserving the frozen argument shapes.
HostRunRecorder and the separately injected report writer are trusted host
capabilities, not subject-facing services. Recording evidence does not validate
an approval, capture a filesystem or execute anything. Task4 must independently
establish bound/context and actual captured observations before giving them to
the writer. The evaluator gets only the RecordVerifier for evidence read paths;
it never accepts successful booleans in place of authenticated captured bytes.
No signing key or writer belongs in an executor/probe/checker container.

Run scope is recomputed from expected tenant/principal/repository/environment.
Run subject includes full Task1 execution_subject (request, source commit,
old/new publications, task/budget/model/config, all artifact bytes and program
bindings), complete trusted context, exact role and repetition. Stages include
this run subject, expected stage ID and exact ordered inputs. Report subjects
are recomputed from this expected binding plus exact referenced run membership;
caller-supplied scope/subject metadata is never adopted as authority.

AgentRun contains role(old/new), repetition(0-based), record(RecordRef), and
pair_record(optional RecordRef). Host journal assignment supplies record IDs.
The authoritative run record contains the whole canonical RunEvidence payload,
including all process/check/probe bytes and final snapshot; this is one aggregate
authenticated record, not unauthenticated individual result dataclasses.
Pair record references both authoritative run records in old,new order.
Every stored payload is rehashed/HMAC-verified and strictly parsed. Public
model_copy/construct or edited report counters do not authenticate themselves.

## Actual runner data shapes

```python
TreeEntry(path: str, kind: Literal["file", "directory"], mode: int,
          digest: str | None = None, size: int = 0)
Snapshot(entries: tuple[TreeEntry, ...])
snapshot.digest_value() -> str  # sha256 of canonical payload

ProcessCapture(
    subject: str, container_id: str,
    started_ns: int, finished_ns: int,  # one host monotonic clock across pair
    exit_code: int | None, terminated: bool, timed_out: bool,
    output_limited: bool, stdout: bytes, stderr: bytes,
)
CheckCapture(check_id: str, process: ProcessCapture,
             probes: tuple[ProcessCapture, ...])
RunEvidence(role: Literal["old", "new"], repetition: int,
            final: Snapshot | None, snapshot_ns: int | None,
            executor: ProcessCapture | None, checks: tuple[CheckCapture, ...])
PairEvidence(repetition: int, old_record: RecordRef, new_record: RecordRef,
             checks: tuple[CheckCapture, ...])
```

Snapshots include an explicit `.` directory entry and every file/directory,
sorted by path. All parents must exist as directories. Regular files require
content SHA256 plus byte size; directories have no digest and size0. Modes are
permission bits up to07777. Paths reject traversal, absolute paths, wildcard
characters, duplicate entries and unsupported types. Entry count and aggregate
byte size respect the signed output-tree ceilings. Directory/root entries count
toward this conservative entry ceiling. No Git-status or ignored-file filtering
is permitted in Task4's capture. No filesystem capture implementation is claimed
here: validate_snapshot validates the supplied complete manifest structure;
the trusted runner must actually walk/hash the complete terminated tree.

A precondition-aborted or uncertain/failed attempt can record executor=None,
final=None and snapshot_ns=None, preserving any actual checks. Never invent a
container or tree to fill these fields. It cannot produce a valid contract
report. Timeout captures retain actual exit/termination/output flags and raw
captured bytes; there is no automatic retry or false observation default.

For checker captures the sole stdout object is strict UTF8 JSON:
`{"check_id":"exact-signed-id","observation":true}`. False is equally valid
observation data. Unknown fields, duplicates (including duplicate JSON keys),
additional objects, skipped output, absent or nonboolean observation, wrong ID,
abnormal checker exit, timeout, unresolved termination or exceeded output limits
block. Subject-probe stdout/stderr/ordinary nonzero exit are captured data for
the checker, not checker results; timeout/signal/incomplete probe captures block.

Bytes use base64 in the strict model JSON wire format. `payload_bytes()` returns
JCS bytes excluding a report's own record reference. Callers should construct
typed models from actual bytes and let the recorder serialize them.

## Stage identity recipe

`identity(value)` is SHA256(JCS(value)); references below use
`identity(record.model_dump(mode="json"))`, binding ID and payload digest.

```python
stage_subject(bound, context, role, repetition, stage_id,
              inputs: tuple[str, ...], probes: tuple[ProcessCapture, ...] = ())
```

For executor, stage_id is literal executor and inputs=(S0_digest,).
For pre checkers, stage_id is the signed check_id and inputs=(S0_digest,).
For post checkers, inputs=(S0_digest, corresponding_final_digest).
For pair checkers, inputs=(S0_digest, old_final_digest, new_final_digest,
old_record_identity, new_record_identity); role is pair. Pair checks occur once,
after both post sets, and use only pair_expected=true.

For each declared subject probe, stage_id is its signed probe_id and inputs has
exactly the designated snapshot digest. For pre/post current means S0/final
respectively; pair initial/old_final/new_final use the corresponding operand.
Probe captures occur after snapshot availability and finish before their checker
starts; checker subject also includes the complete ordered probe capture tuple.
Probe order/cardinality follow subject_probes. Each check/probe/executor has its
own container capture identity; duplicate identities within a run are rejected.
The actual runner must additionally enforce its described mount/process isolation.

Both precondition sets must finish before either executor starts; final snapshot
time follows executor termination; post checks start after snapshot time; pair
checks/probes start after both completed post sets. An observed false precondition
is retained as GUARD_FAILED, never repaired into a permitted executor startup.
Task4 must enforce these stages BEFORE effects, not use evaluation after an
unsafe startup as a substitute for execution preflight.

## Reports and component meaning

ContractReport contains valid, blockers, run, ter/pip/bsr Count(numerator,
denominator), traces and authenticated record. Each trace retains check_id,
role, observation(bool or None), expected bool and observation-validity flag.
For each scoring role numerator counts observed true; denominators count its
own declared checks, excluding guards. New target/invariant require true;
spillover true means forbidden behavior was triggered. Old target is evaluated
against its explicit signed expectation, so a valid old report can have TER0/1.
Invalid/missing observations never become false/pass defaults. Invalid whole
run records produce unavailable0/0 components with blockers, never success.

DifferentialReport retains old/new ContractReport, one trace per pair binding,
all three path change sets and its authenticated record. S0->old and S0->new
both enforce allowed/forbidden scopes using M4 anchored POSIX glob semantics.
Identical out-of-scope changes on both sides block despite empty old->new delta.
Deletion, creation, type/content/mode and directory mode changes are included.
Root mode changes conservatively block. Empty allowed scope permits no changes;
empty required scoring collections or paired checks cannot pass vacuously.

RepetitionReport contains the complete provided pair reports, blockers and its
authenticated record. It requires exactly each zero-based predeclared repetition
once, authenticates all reports, and requires all pairs to pass. Mixed observation
or blocker outcomes yield UNSTABLE_TWIN_RUN. Negative valid outcomes are retained.
No RCS aggregate, statistical threshold, provider cost or real-Agent inference.

Task4 owns the exact approved attempt manifest and must pass every planned pair,
not choose favorable reruns. The journal retains all appended attempts; this
evaluator does not run retries or infer a new study/attempt policy. Task6 must
bind the prepared record to this exact runner-produced group and references,
require valid=True after verify_report, and perform fresh Task2 authorization,
source/view validation plus execution-approval checks at effect boundaries.
verify_report authenticates negative reports too; authentication is not success.
Invalid/incomplete underlying evidence cannot authenticate as completed runs.

## Actual RED/GREEN and verification

1. Initial import discovery failed (exit2). A wrong core module import was a
   skeleton error and was corrected; neither is claimed as behavioral RED.
2. With real fixture publication and journal working, stub evaluation produced
   six actual assertion failures and one pass. Implemented strict result parsing,
   counts and expectation/status binding:23focused passed4.43s.
3. Initial pair methods absent produced13failures; after callable skeleton,
   positive pair and mixed-repeat assertions failed (2actualRED). Implemented
   paired operands, whole-tree deltas/scopes and group logic:36passed7.67s.
4. Expanded probe/auth/tree tests yielded2failed60passed: legitimate declared
   probe rejected; tampered underlying pair payload was not rechecked by an
   existing report. Added probe input/timing binding and pair reauthentication:
   62passed12.63s.
5. Duplicate checker/executor container test actually failed with false success;
   rejected repeated identities.69focused passed14.63s.
6. Aborted attempt could not honestly record absent process/tree (3validation
   errors,1failed); nullable RunEvidence plus internally required completed
   evidence fixed it.70focused passed14.75s; full927passed66.32s.
7. Final task checklist exposed empty differential bindings/records passing
   vacuously. Actual1assertionRED; added a nonempty paired-check gate. Final
   focused71passed14.81s; final full928passed66.51s (857baseline+71new),
   raw task-3-full-final.log. Earlier full927 output remains separately in
   task-3-full-green.log; it is not represented as the final candidate run.
8. In-process counter mutant returned0/0: explicit component assertion fails,
   exit1,1failed0.98s. In-process scope bypass makes identical out-of-scope
   changes falsely valid: exit1,1failed0.98s. No files were mutated. Raw logs:
   task-3-counter-mutant.log and task-3-scope-mutant.log.
9. Ruff normal/no-ignore and C901,PLR0911,PLR0912,PLR0915 under both modes pass;
   Mypy90files passes. Scanner inventory91each=90Python+pyproject, matching
   filesystem enumeration. Formatting affected only the four new files.
10. uv sync --locked --offline passed46resolved/45checked. Protected baseline
    diffs (schemas, pyproject, uv.lock, frozen files, M1-M4 implementation and
    Task1/2 tests) are empty. Both frozen hashes and whitespace checks pass.

## Bounded conclusion

This is authenticated synthetic engineering evidence for C1/C2/C5, prospective
RQ3 and System/replacement-mechanism paragraphs. It is not C3/C4/RQ1/RQ4
empirical evidence, human benchmark truth, actual Docker execution or M5 exit.
Task4 still owns process isolation/capture and executable preflight; Task5/6 own
durable action/pointer/prepared transactions, approvals, activation and rollback.
Current policy/source freshness remains their effect-time obligation.

Original M5Aug22-24schedule is missed. No date/study/gate waiver is claimed.
Independent review of the exact technical candidate is the next step.
未开始下一模块（M6）；本子任务未执行M5-4及以后任务。
