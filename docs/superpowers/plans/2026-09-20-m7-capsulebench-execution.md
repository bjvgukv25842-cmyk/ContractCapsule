# M7 CapsuleBench Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` to implement this plan task-by-task. The plan stops at the M7 engineering exit gate and does not start M8 pilot runs.

**Goal:** Build the reproducible CapsuleBench task/condition substrate, budget-parity providers, and idempotent experiment record/replay harness required before pilot authorization.

**Architecture:** Benchmark packages are immutable, filesystem-addressed task inputs. A common `ContextProvider` interface produces a condition-labeled-independent `ContextArtifact` with a bounded UTF-8 payload and digest. The experiment harness consumes validated task/config records, refuses live execution unless an explicit preflight gate is present, and writes append-only run records with infrastructure failures separated from task outcomes.

**Tech Stack:** Python 3.12, Pydantic v2, PyYAML, pytest, existing CCS-2.1 compiler/adapters, JSONL and SHA-256.

**Spec:** `docs/spec/CCS-2.1.md` and `docs/superpowers/plans/2026-07-30-contract-capsule-fse-2027-execution-plan.md`, especially Sections 5, 6, 9, and M7.

## Global Constraints

- Published capsule cores remain immutable; benchmark files use repository commit and content digests.
- Gold labels are candidates until human approval; this implementation must never infer approval from generated files.
- Scoring is condition-blind and runs without an agent.
- B1--B4 and CC use one declared maximum runtime-view budget; P0 overflow fails closed.
- Existing valid `run_id` records are never overwritten; infrastructure retries retain distinct attempt IDs.
- No M8 pilot, M9 full experiment, or empirical claim is started by this module.
- Every AI-assisted change is appended to `research/ai-usage-ledger.jsonl` and the module report.

## Review Focus

- Path traversal or symlink escape in task packages must be rejected before loading.
- Duplicate task IDs, condition IDs, run IDs, and YAML keys must fail closed.
- A budget mismatch or tokenizer failure must block comparison rather than silently truncate.
- A task failure must not be classified as infrastructure failure, and retry metadata must not replace the original record.
- A scorer must execute only declared relative test commands and must not trust condition-provided labels.

## Task List

### Task 1: Benchmark package schema and manifest

**Files:**
- Create: `benchmark/__init__.py`, `benchmark/schema.py`, `benchmark/loader.py`, `benchmark/benchmark-manifest.json`
- Populate: `benchmark/tasks/` with 24 screened candidate package manifests (human approval remains pending)
- Test: `tests/integration/test_benchmark_tasks.py`

**Interfaces:**
- Produces `TaskSpec`, `GoldSpec`, `RepositoryLock`, `BenchmarkManifest`, `load_manifest(path)`, `load_task(path)`.
- `TaskSpec.task_id`, `TaskSpec.repository_commit`, `TaskSpec.approval_status`, and `TaskSpec.max_runtime_seconds` are stable fields consumed by Tasks 2 and 3.

- [ ] Write failing tests for manifest cardinality, unique IDs, safe paths, digest validation, approval status, and task loading.
- [ ] Implement strict Pydantic/YAML loading with duplicate-key rejection and symlink/path containment checks.
- [ ] Add 24 non-executable screened candidate records with explicit `human_approval: pending` and source/license provenance fields; do not claim them as approved truth.
- [ ] Run the focused benchmark tests and commit.

### Task 2: Six condition providers and budget parity

**Files:**
- Create: `baselines/__init__.py`, `baselines/providers.py`, `baselines/budget.py`
- Test: `tests/integration/test_baseline_budget_parity.py`

**Interfaces:**
- Consumes `TaskSpec` and package-relative context files from Task 1.
- Produces `Condition` enum (`B0` through `CC`), `ContextArtifact`, `ContextProvider`, `provider_for(condition)`, and `assert_budget_parity(artifacts, budget)`.

- [ ] Write failing tests proving all six conditions share the interface, all bounded artifacts fit the same budget, and overflow is rejected.
- [ ] Implement deterministic providers for native, full-context, RAG, summary, atom-only, and CCS views. Provider outputs contain no gold labels or condition instructions.
- [ ] Run the focused provider tests and commit.

### Task 3: Preflight, idempotent run records, and condition-blind scoring

**Files:**
- Create: `experiments/__init__.py`, `experiments/models.py`, `experiments/preflight.py`, `experiments/run.py`, `experiments/score.py`
- Test: `tests/integration/test_experiment_replay.py`

**Interfaces:**
- Consumes Task 1 `TaskSpec`/manifest and Task 2 `ContextArtifact`.
- Produces `RunRecord`, `RunStore`, `preflight_config()`, `run_once()`, and `score_task()`.

- [ ] Write failing tests for stable run IDs, no overwrite, infrastructure-only retry eligibility, dry-run refusal without a preflight receipt, and scorer condition blindness.
- [ ] Implement strict YAML/JSON config parsing, adapter metadata capture, append-only JSONL records, and bounded subprocess scoring of declared tests.
- [ ] Keep live-agent execution opt-in behind a signed/hashed preflight receipt; default CLI mode is dry-run.
- [ ] Run the three M7 focused suites and commit.

### Checkpoint: M7 engineering substrate

- [ ] `uv run pytest tests/integration/test_benchmark_tasks.py tests/integration/test_baseline_budget_parity.py tests/integration/test_experiment_replay.py -v` passes.
- [ ] `uv run ruff check benchmark baselines experiments tests/integration/test_benchmark_tasks.py tests/integration/test_baseline_budget_parity.py tests/integration/test_experiment_replay.py` passes.
- [ ] Manifest contains 24 screened records, with no record represented as human-approved evidence.
- [ ] Add M7 module report, decision-log entry, claim-evidence update, and AI-use ledger entry.
- [ ] Stop at the human M7 exit decision; explicitly state that M8 has not started.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Public repositories cannot be licensed or reproduced in this environment | High | Keep candidate records explicitly pending; require human/source verification before G2. |
| Provider implementations leak condition labels or gold truth | High | Condition-blind payload tests and scorer-side label isolation. |
| Agent binaries/models are unavailable or drift | High | Preflight records exact metadata and blocks live execution without a receipt. |
| Large task packages make tests slow | Medium | Validate manifests and fixture metadata in M7; defer network checkout/execution to approved pilot. |

## Open Questions

- Human authors must approve or exclude each candidate task and independently review at least 25% before G2.
- The author must choose the pilot budget and freeze actual Codex/Claude model identifiers in `experiments/configs/agents.yaml`.
