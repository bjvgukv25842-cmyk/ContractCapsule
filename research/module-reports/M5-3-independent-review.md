# M5-3 independent review

Date: 2026-09-10. Reviewer: independent Codex task m5_3_task_review.

Technical target: 20cb819c19c6c4c6edf632ba1d6d21bc0e53fffd.
Requested base: f161910952cbbefc367198a373cce21b6fee5a16.
Worktree: /Users/litmus/Documents/Contract Capsule/.worktrees/m5-validation-swap.

Verdict: **Spec: REQUEST CHANGES. Quality: REQUEST CHANGES**, for the single
correctness finding below. No separate readability, architecture, dependency,
or performance finding is asserted. This is not an M5 exit review.

## Required finding

### P2 — Reject container identity reuse across the roles of one twin pair

Location: src/contractcapsule/validate/behavior.py:157, with the same omitted
consistency check at :199 in _pair_traces.

_read_run rejects duplicate executor/check/probe container identities within
one RunEvidence, but _pair_runs simply returns the independently read sides,
and _pair_traces checks only individual checker/probe identity uniqueness.
Consequently compare_runs can persist valid=True with no blockers when the
old and new executors use the same container ID, or when a pair checker claims
the old executor's container ID. verify_report accepts both resulting reports.
All relevant identities are already captured and authenticated; no additional
Docker integration or new schema is necessary to detect this contradiction.

Accepted ADR-0005 Decision 3 requires each subject executor to use its own
restricted container, and every untrusted probe to remain in a separate
container from the trusted checker. A host capture assembled by a runner that
incorrectly restarts/reuses a container should not pass the independent
evaluator's existing container-isolation consistency check merely because the
reuse crosses the old/new/pair boundary. This is a detectable record-consistency
gap, not a claim that an untrusted caller can sign records or that Docker has
been escaped. The implementation handoff honestly claims within-run uniqueness;
the concern is that this narrower check does not cover the paired isolation
requirement of the accepted design.

Reproducer: diagnostics.py in this same external directory. From the worktree:

```text
PYTHONPATH=. .venv/bin/python /tmp/cc-m5-3-review.A5K8mb/diagnostics.py
```

The diagnostic constructs normal published test capsules and authenticated
synthetic host captures through the existing Harness and public recorder. It
uses old executor timestamps20..30, new executor31..35 for the shared-executor
case, both final snapshots40, post checks50..51, and pair checker60..61. Thus
the finding does not depend on overlapping execution timestamps. It reports:

```text
{"case": "distinct_containers", "valid": true, "blockers": [], "authenticated": true}
{"case": "same_executor_container", "valid": true, "blockers": [], "authenticated": true}
{"case": "pair_checker_in_executor_container", "valid": true, "blockers": [], "authenticated": true}
AssertionError: Cross-role container reuse was accepted
```

Command exit1 is an actual assertion failure. The first diagnostic attempt
failed earlier due to macOS /var being a symlink in tempfile's path; resolving
the temporary path fixed the fixture setup. That earlier failure is not
behavioral evidence. All observations here are synthetic, not actual Docker
execution. A compliant future Task4 runner could independently prevent reuse;
that does not remove the inexpensive consistency check from this evaluator's
existing role/phase/container validation responsibility.

Minimum fix scope: in Task3 behavior.py, validate disjoint container identities
across both runs and the complete pair check/probe collection, using the already
authenticated evidence. Reuse this path during report verification. Add focused
negative tests for cross-run executor reuse and pair subject/checker reuse,
plus a distinct-container positive control. No global uniqueness policy across
separate repetition groups, attempt selection, Docker execution, activation,
approval redemption, or M1-M4 changes is requested. The existing synthetic
reuse of IDs across different repetitions is not the finding.

## Reviewed evidence and satisfactory boundaries

Read AGENTS.md, both complete frozen baselines, complete accepted ADR-0005,
the derived M5 execution plan, latest decision-log entries, Task3 brief and
handoff report. Read all four new technical/test files and the shared journal
and relevant Task1 identity/type implementations. The code-review-and-quality
skill was read and applied. No subagent was used.

The supplied task-3-review.diff exactly matches the requested four-file Git
diff: SHA256 b64e402adf384abf57bd592cdd2353275e82ace0b4cbb11468171dc4409bad39.
Additional governance changes in the base-to-head range were not mistaken for
Task3 implementation. Initial and final Git status were clean.

Both frozen SHA256 values match:

- CCS-2.1: aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c.
- Frozen plan: 7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0.

The implementation correctly recomputes expected request/principal/role/repeat
subjects and verifies exact canonical payloads against the authenticated
journal. Transport construction and edited report counters are not credentials.
Stage subjects cover signed program configuration, ordered snapshot inputs,
and full probe captures. Pair observations bind the ordered old/new record
identities and snapshots rather than inventing per-state differential passes.

Target/invariant/spillover counters remain separate, guards do not enter their
denominators, old target expectations are explicit, malformed observations do
not become false/pass defaults, and valid unfavorable observations remain
stored. Both source-relative complete-tree manifests enforce scope, retaining
the old/new delta separately. Structural validation covers parents, modes,
deletions, additions, safe paths, entry count, and aggregate sizes.

Repetition membership is exact and negative/mixed outcomes block. The choice
of every authorized attempt belongs to the forthcoming trusted runner/state
owner, as explicitly documented; this review does not demand retry policy or
activation implementation from Task3. Initial-tree completeness, actual
mount/process isolation, source/view/approval origin, and effect-time freshness
are honestly declared Task4/6 responsibilities rather than falsely certified
by synthetic Task3 fixtures. No additional concrete transport-data blocker was
established during this bounded review.

The implementation's full-suite log was inspected and ends928 passed in66.51s.
That is implementation evidence, not an independently rerun test result. The
reviewer executed only the targeted external diagnostic above, no full suite,
Docker execution, formatter, source edit, index write, or governance mutation.
All reviewer-created files are in this external temporary directory.

The original Aug22-24 M5 dates are missed. This review grants no schedule,
research, M5 exit, or M6 waiver. Parent/controller retains the author gate and
the responsibility to record this AI review in governance.
