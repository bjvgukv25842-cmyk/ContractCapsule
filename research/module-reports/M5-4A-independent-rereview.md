# M5-4A Independent Scoped Re-review

Date: 2026-09-13

## Verdict

- Spec/task compliance: **FAIL - REQUEST CHANGES**
- Quality: **FAIL - REQUEST CHANGES**
- Finding count: 1 P2

The repair closes the reported empty-list, object, invalid-JSON, missing-field,
and wrong-type paths, and the tested owned-resource cleanup paths are sound.
However, a bounded malformed Docker response can still escape as raw
`RecursionError`, so the requested stable `RunnerError`/`StageError` contract is
not complete.

## Exact Scope and Isolation

- Audited source: `/private/tmp/contract-capsule-m5-4a-rereview.pObpKI/source`
- Physical path verified with `pwd -P`.
- Audited HEAD: `ea6855830e50f58fb9cbe11f861bdd024700080c` (detached, clean).
- Repair base: `03d9ba42d142a55254d11280099226d5b8ef200a`.
- Repair commit: `6e798c761d008a96ef4b529995890f95fd9a7d5e`.
- `docker_lifecycle.py` and `test_docker_stage.py` have no changes from
  `6e798c7` through `ea68558`.
- Reviewed only `DockerLifecycle.preflight`, `DockerLifecycle.state`, their
  direct error/cleanup behavior, and malformed-response regression tests.
- Twin orchestration, attempt selection, and unfinished M5-4B were excluded.
- No audited branch/source/Git state was modified. Tests and caches were kept
  outside the source tree.

## Normative Inputs

Read completely:

- `AGENTS.md`
- `docs/spec/CCS-2.1.md`
- `docs/superpowers/plans/2026-07-30-contract-capsule-fse-2027-execution-plan.md`
- accepted `docs/adr/0005-m5-executable-contracts-and-swap.md`
- current M5 decision-log entries through M5-012

Verified hashes:

- CCS-2.1: `aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c`
- Frozen execution plan: `7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0`
- Accepted ADR-0005: `c4457f5da29903261ea7ce58c68e28c43cbdfb74eb55e70a8ff5c1d1617921a0`

The frozen M5 dates and G1/G2/G3 dates are missed. This audit does not revise
the schedule, advance M5, authorize M6, or establish empirical RQ3 evidence.

## Finding

### 1. [P2] Deeply nested Docker JSON leaks raw `RecursionError`

Locations:

- `src/contractcapsule/swap/docker_lifecycle.py:41`
- `src/contractcapsule/swap/docker_lifecycle.py:151`
- Direct stage consequence: `src/contractcapsule/swap/docker_runner.py:77`

Both methods call `json.loads` inside handlers that normalize `OSError`,
`TypeError`, `ValueError`, `KeyError`, and `JSONDecodeError`. Python's decoder
raises `RecursionError` for a sufficiently nested valid JSON value. A depth
10,000 payload is about 20 KiB, well below `control()`'s 1 MiB output limit.

Minimal reproduction:

```python
payload = b"[" * 10_000 + b"0" + b"]" * 10_000
lifecycle.control = lambda *args, **kwargs: payload
lifecycle.preflight()          # raw RecursionError
lifecycle.state("a" * 64)     # raw RecursionError
```

Exact executable reproduction:

- `/private/tmp/contract-capsule-m5-4a-rereview.pObpKI/diagnostics/repro_nested_json.py`
- Output log:
  `/private/tmp/contract-capsule-m5-4a-rereview.pObpKI/logs/nested-json-repro.log`

Observed output:

```text
preflight RecursionError maximum recursion depth exceeded while decoding a JSON array from a unicode string
state RecursionError maximum recursion depth exceeded while decoding a JSON array from a unicode string
```

Impact: malformed daemon output still blocks execution, and `run_stage`'s
`finally` still attempts cleanup, but callers do not receive the required stable
`RunnerError`/`StageError` classification or structured stage failure. This is
the same boundary class as the approved repair, not an M5-4B orchestration
finding.

Minimal repair: normalize `RecursionError` raised by Docker JSON decoding in
both `preflight()` and `state()` to their existing stable `RunnerError`
messages. Add direct preflight/state regressions and one stage-level regression
showing `StageError` plus exact cleanup after resources exist.

## Passing Evidence

### Committed regression at repaired HEAD

Command selected the two committed node IDs. Result:

```text
4 passed in 0.18s
```

Log:
`/private/tmp/contract-capsule-m5-4a-rereview.pObpKI/logs/committed-malformed.log`

The same HEAD tests executed against base `03d9ba4` produced four genuine
failures: raw `IndexError`, raw `KeyError`, raw `JSONDecodeError`, and a missing
state-field case that did not raise. This confirms regression sensitivity.

Log:
`/private/tmp/contract-capsule-m5-4a-rereview.pObpKI/logs/base-regression-red.log`

### Independent shape and cleanup diagnostics

Diagnostic source:
`/private/tmp/contract-capsule-m5-4a-rereview.pObpKI/diagnostics/test_malformed_shapes.py`

Result:

```text
65 passed in 1.28s
```

Coverage includes:

- malformed/empty/scalar/list/object image and state envelopes;
- every consumed image field: `Id`, `Os`, `Architecture`;
- every consumed state field: `Id`, `State`, `Running`, `Status`, `ExitCode`,
  `OOMKilled`, `Error`;
- missing fields and wrong JSON types, including rejecting booleans as ints;
- valid responses with ordinary Docker extra fields;
- identity/platform mismatch remaining distinct from malformed data;
- real Docker malformed initializer state -> `StageError` and no retained exact
  containers/volume;
- real Docker malformed subject state -> blocked capture, conservative
  unterminated status, and no retained exact containers/volume.

Log:
`/private/tmp/contract-capsule-m5-4a-rereview.pObpKI/logs/final-diagnostics.log`

Audit-only Ruff result: `All checks passed!`

Log: `/private/tmp/contract-capsule-m5-4a-rereview.pObpKI/logs/final-ruff.log`

Docker used without pull:

```text
29.5.2 linux/arm64
sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203 linux/arm64
```

## Review Axes

- Correctness: original cases repaired; one residual malformed decoder
  exception remains.
- Readability: explicit strict built-in type checks are understandable; long
  state predicate is dense but not itself blocking.
- Architecture: validation remains at the Docker trust boundary and introduces
  no dependency or cross-module coupling.
- Security: tested responses fail closed and exact resources clean up; raw
  exception classification remains the finding above.
- Performance: response size remains bounded; no material regression observed.

No full-suite result is attributed to this reviewer. The parent controller's
separate full regression is outside this report. Known unfinished `git_tree`
complexity and M5-4B behavior were not reviewed and do not affect this scoped
finding.

## Harness Notes

Two audit setup mistakes were excluded from evidence and retained rather than
silently discarded: an initial diagnostic command had an invalid Ruff
environment assignment/log destination, and an initial base-sensitivity command
mistyped a pytest node and collected no tests. Their logs are respectively
`logs/diagnostics-initial-harness.log` and
`logs/base-regression-red-harness-error.log`. Corrected commands produced the
results reported above.
