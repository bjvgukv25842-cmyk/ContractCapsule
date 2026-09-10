# M5-3-R1 independent rereview

Date: 2026-09-10. Reviewer: Codex task m5_3_task_review.

Target: f94412dc4dc80125cbc1ffa2e7b0e54a6c0aa017.
Original technical target: 20cb819c19c6c4c6edf632ba1d6d21bc0e53fffd.
Worktree: /Users/litmus/Documents/Contract Capsule/.worktrees/m5-validation-swap.

**M5-3-R1: ADDRESSED. Spec: PASS. Quality: PASS.** No actionable finding
remains in the original finding or the bounded repair diff. This verdict
completes the prior Task3 review with its one finding resolved; it is not an
M5 module exit or a review of subsequent runner/controller work.

## Scope and evidence inspected

Read the tracked original M5-3-independent-review.md, task-3-brief.md, appended
FIX ROUND 1 handoff, latest decision-log entries including itemized author
approval M5-009, and complete task-3-fix1-review.diff. Reused the complete
frozen specification, frozen execution plan, accepted ADR-0005 and review skill
already read in this review task. Both frozen hashes were rechecked and match:

- CCS-2.1: aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c.
- Plan: 7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0.

The supplied repair diff is exactly the two-file technical Git diff with
unified context10 from20cb819 to f94412d. Its SHA256 is
f182c29a4afa54f44dcc4afa01e76527d15a26881d50023a721e50cac7c3a58a.
Only behavior.py and test_behavior_contract.py are technical repair scope.

The existing dirty research/module-reports/M5-3-implementation.md belongs to
the controller; it was observed and left untouched. No source, index,
governance, schema, dependency, frozen input or original report was changed by
the reviewer. All newly created reviewer artifacts are outside the repository.

## Why the finding is resolved

behavior.py:517 introduces one stateless helper which collects both executor
IDs and every old/new/pair checker and subject-probe ID. It rejects any duplicate
in that single combined collection. _pair_runs invokes it after independently
authenticating the two complete runs; _pair_traces invokes it again after
authenticating and binding the full PairEvidence. Therefore the code covers
cross-run executor reuse, cross-role checker/subject reuse, old/new probes,
and collisions between different pair bindings rather than only collisions
inside one check. It needs no additional transport data or global state.

The existing verify_report differential path invokes _pair_runs and
_pair_traces; repetition verification recursively invokes differential
verification. The new guard consequently runs both while deriving a report and
while accepting an already persisted report. The helper has no state beyond
the passed pair, so it does not introduce a cross-repetition uniqueness rule.
Counts, phase/expectation semantics, snapshots, negative-outcome preservation,
approval policy and public interfaces are unchanged.

The ten added tests exercise nine collisions plus one positive case with two
pair check/probe bindings. Rejected records also test differential/group
verification. The fixture's sequential timestamps avoid making the isolation
finding depend on an impossible simultaneous process identity.

## Independent targeted diagnostic

The remaining doubt was whether reports persisted as successful under the
previous guardless implementation would actually be rejected, because the
new tests primarily verify reports already derived as invalid after repair.
The external diagnostics.py tests this directly through genuine fixture
publication and authenticated host record/report storage. It temporarily
disables only the helper in the diagnostic Python process, derives and signs
the prior defective success report, restores the helper, and checks evaluation
and recursive verification. No repository source is patched and no HMAC or
record verifier is bypassed. A group wrapping that prior success is explicitly
marked invalid/incomplete, avoiding a claim of complete three-pair success.

Command run from the worktree:

```text
PYTHONPATH=. .venv/bin/python /tmp/cc-m5-3-r1-review.kbBog4/diagnostics.py
```

Actual exit0, output:

```text
shared_executor: evaluation blocks; previously signed success and containing group rejected
checker_old: evaluation blocks; previously signed success and containing group rejected
probe_prior_checker: evaluation blocks; previously signed success and containing group rejected
distinct pair IDs with IDs reused across three repetitions: complete group passes and verifies
```

This independently confirms representative cross-run, subject/checker and
cross-pair-binding failures plus the complete repeated-success control.
All process captures are explicitly synthetic; no Docker or Agent execution
is claimed.

## Implementation verification and limits

Inspected implementation raw logs: initial RED9failed/1passed/71deselected;
helper-bypass mutant9failed/1passed/71deselected; final focused81passed17.56s;
full938passed70.22s. The red/mutant failures are named assertion failures for
the nine collision cases. These counts remain implementation evidence, not
reviewer reruns. No full suite, formatter, lint scan or Docker execution was
repeated in this bounded review. The repair is small and directly reuses the
existing authenticated read/verify paths without interface or dependency
expansion; no repair-introduced correctness or maintainability defect was found.

Task4 must still establish actual container/mount isolation and trustworthy
capture; Task5/6 own durable state, exact attempt binding and activation-time
authorization. Synthetic Task3 tests do not establish those later results,
research outcomes, M5 exit, M6 authorization or a schedule waiver.
