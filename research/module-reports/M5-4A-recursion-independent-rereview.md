# M5-4A Recursion Repair Independent Re-review

Date: 2026-09-13

## Verdict

- Prior finding 1, raw `RecursionError`: **ADDRESSED**
- Scoped spec/task compliance: **PASS**
- Scoped quality: **PASS**
- New actionable findings: none

## Target and Scope

- Physical audit copy:
  `/private/tmp/contract-capsule-m5-4a-recursion-rereview.W969S3/source`
- Detached audited commit:
  `d5ad6814feebfc7bd9cfd8251539c1aa5d3081b0`
- Governance base: `b6ba68337ffd5c3bca26aca917f45fd884938ca8`
- Prior technical target: `ea6855830e50f58fb9cbe11f861bdd024700080c`
- Read the supplied 165-line `task-4a-recursion-review.diff` and complete
  34-line `task-4a-recursion-fix-report.md` before verification.
- Reviewed only the two Docker response-normalization tuple changes and five
  recursion regressions. M5-4B/twin orchestration was excluded.
- The previous audit directory, report, diagnostics, and logs were not changed.

The committed diff changes only:

- `src/contractcapsule/swap/docker_lifecycle.py`: replace redundant explicit
  `JSONDecodeError` entries with `RecursionError` in the existing preflight and
  state normalization tuples. `JSONDecodeError` remains covered through its
  `ValueError` base class.
- `tests/integration/test_docker_stage.py`: five behavior regressions covering
  direct image/state normalization, preflight `StageError`, initializer-state
  cleanup, and subject-state conservative blocking/cleanup.

## Prior Finding Resolution

The original depth-10,000 payload is approximately 20 KiB and remains below the
Docker control output limit. Independent exact-error assertions now observe:

```text
preflight RunnerError RecursionError malformed image inspection
state RunnerError RecursionError malformed container state
```

Both public methods therefore expose the stable existing `RunnerError` messages
while retaining the decoder exception as `__cause__`. The stage regressions
also prove:

- malformed image preflight becomes `StageError` with no retained resources;
- malformed initializer state becomes `StageError`, and exact created
  containers/volume are absent afterward;
- malformed subject state returns a conservative blocked `StageResult`, keeps
  real stdout, does not certify termination or a tree snapshot, and leaves no
  exact created container/volume behind.

This closes the prior finding without widening exception handling, changing
limits, changing public APIs, or touching orchestration semantics.

## Independent Verification

Docker preflight, without image pull:

```text
29.5.2 linux/arm64
sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203 linux/arm64
```

Focused recursion plus original malformed-response tests:

```text
9 passed, 28 deselected in 1.67s
```

This includes all five new recursion nodes and the four original malformed
image/state nodes.

Scoped static checks:

```text
Ruff: All checks passed!
Complexity C901/PLR0911/PLR0912/PLR0915: All checks passed!
Mypy: Success: no issues found in 2 source files
```

Independent audit-only diagnostic:

- `/private/tmp/contract-capsule-m5-4a-recursion-rereview.W969S3/diagnostics/verify_exact_error.py`

Logs:

- `logs/focused-recursion-and-original.log`
- `logs/exact-error.log`
- `logs/scoped-ruff.log`
- `logs/scoped-complexity.log`
- `logs/scoped-mypy.log`

No full suite was rerun or attributed to this reviewer, as requested. The
implementation report's full-suite result is treated as author evidence, not
independent evidence. One initial combined static command contained invalid
paths for complexity/Mypy; those results were excluded and both commands were
rerun successfully with corrected paths.

## Review Axes

- Correctness: exact stable errors and cleanup outcomes are independently
  demonstrated.
- Readability: the minimal tuple substitution is direct and preserves the
  existing handling structure.
- Architecture: validation remains at the Docker response boundary; no new
  abstraction or dependency is introduced.
- Security: malformed bounded output blocks execution, cannot certify state,
  and tested owned resources are removed exactly.
- Performance: no new processing or unbounded operation is introduced.

This is a scoped technical PASS only. It does not complete M5-4B, M5, any
activation gate, M6, or formal experimental evidence.
