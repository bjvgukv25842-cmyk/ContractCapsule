# M8 Pilot Readiness and Survival Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare and execute the M8 pilot gate without allowing unapproved benchmark tasks, unfrozen agent metadata, or incomplete protocol inputs to produce pilot evidence.

**Architecture:** Add a deterministic, fail-closed pilot planner beside the M7 run harness. It validates the six-task/ four-condition/ two-repetition design, binds the schedule to the loader-attested benchmark and protocol digests, and emits a structured readiness report before any agent call. The current screening manifest must be refused; no pilot result is created until the author supplies G2-approved task truth and a signed preflight receipt.

**Tech Stack:** Python 3.12, Pydantic v2, PyYAML, existing M7 loader/run store/preflight APIs, JSON and JSONL, SHA-256, pytest, Ruff, Mypy.

**Spec:** `docs/spec/CCS-2.1.md`, `docs/superpowers/plans/2026-07-30-contract-capsule-fse-2027-execution-plan.md` (M8), and `research/protocol.md`.

## Global Constraints

- The two frozen baseline files and `research/protocol.md` remain read-only; a protocol change requires a dated author-approved amendment.
- M8 pilot scope is exactly 6 stratified tasks, B0/B2/B4/CC, Codex only, 2 repetitions, 48 scheduled cells.
- Every task must be human-approved, executable, source-verified, immutably committed, license-verified, and have non-empty target/invariant/spillover checks before a run can start.
- Agent model/version/binary identity and an authenticated preflight receipt are mandatory; unavailable metadata is recorded as unavailable and never guessed.
- Pilot outputs are append-only and versioned; no retry, rerun, or external outage may replace an unfavorable valid outcome.
- No M9 work, full-study run, TER/PIP/BSR claim, or empirical RQ claim starts in this module.

## Review Focus

- A screening task marked pending must fail the pilot gate before any adapter call.
- A six-task selection with duplicate IDs, missing strata, or a non-48 schedule must fail closed.
- A protocol or benchmark digest mismatch must invalidate the plan rather than silently refresh it.
- A preflight receipt with missing model/version, unsigned metadata, or binary drift must block execution.
- Existing pilot output must never be overwritten or treated as a fresh run.

### Task 1: Deterministic M8 pilot gate and schedule

**Files:**
- Create: `experiments/pilot.py`
- Test: `tests/integration/test_pilot_gate.py`

**Interfaces:**
- `PilotConfig` validates the exact M8 scope and six explicit task strata.
- `PilotRunSpec` identifies one immutable task/condition/repetition cell.
- `PilotGateReport` records `ready`, blockers, warnings, digests, and the 48-cell count.
- `load_pilot_config(path)`, `validate_pilot_inputs(config, manifest_path, protocol_path)`, and `build_pilot_schedule(config)` are deterministic and side-effect free.

- [x] Write failing tests for pending-task refusal, duplicate/missing strata, exact condition/repetition cardinality, protocol/manifest digest binding, and deterministic schedule ordering.
- [x] Run the focused tests and observe the expected failures before production code exists.
- [x] Implement strict YAML loading, immutable digest checks, loader-backed task validation, and structured blocker codes.
- [x] Run the focused gate tests to green.

### Task 2: Pilot configuration and non-destructive gate command

**Files:**
- Create: `experiments/configs/m8-pilot.yaml`
- Create: `results/pilot/.gitkeep`
- Modify: `experiments/pilot.py`
- Test: `tests/integration/test_pilot_gate.py`

**Interfaces:**
- `python -m experiments.pilot --config experiments/configs/m8-pilot.yaml --check` writes only a readiness report and exits nonzero when G2 inputs are absent.
- The checked-in configuration is explicitly non-executable (`dry_run: true`, no model/version/binary), and cannot be mistaken for pilot data.
- A future live check must supply the out-of-tree preflight signing key with
  `--preflight-key`; the key is never committed or printed.

- [x] Add tests proving the checked-in screening configuration produces blockers and never creates a run record.
- [x] Implement the CLI with atomic report creation, signature-key plumbing, and no adapter/network invocation.
- [x] Run the CLI test and inspect the JSON report.

### Task 3: M7 residual closure and research evidence

**Files:**
- Create: `research/module-reports/M8-2026-09-22-implementation.md`
- Create: `research/pilot-report.md`
- Modify: `research/decision-log.md`
- Modify: `research/claim-evidence-matrix.md`
- Modify: `research/ai-usage-ledger.jsonl`

- [x] Record the M7 residuals that prevent a legitimate pilot: screening-only manifest, absent immutable commits/licenses/gold checks, fewer than three verified language ecosystems, and no frozen agent model/version.
- [x] Record the gate execution, blocker codes, absence of pilot observations, and the exact frozen-file hashes.
- [x] Preserve the fact that no external outage or retry was converted into an experiment result.
- [x] Run focused M7 regression tests plus the M8 gate tests, Ruff, Mypy, JSONL validation, and `git diff --check`.
- [x] Stop at the M8 G2 survival decision; do not start M9.

## Exit Gate

M8 engineering execution is complete only when the gate is deterministic and
fail-closed, the current environment has been checked, no invalid pilot run has
been emitted, and the report clearly distinguishes readiness evidence from
pilot observations. Proceeding to an actual 48-run pilot requires a later
author decision supplying the missing G2 inputs; this plan does not invent them.

Recorded outcome (2026-09-22): the engineering gate is complete and refused the
current screening manifest with exit status `2`; the empirical 48-run pilot is
deferred until the author-controlled G2 inputs are supplied.
