# M7 CapsuleBench Engineering Substrate

Date: 2026-09-22 (Asia/Shanghai)

## Scope and status

M7 was authorized for engineering implementation on branch
`codex/m7-capsulebench`. The implementation candidate is the commit range
from M6 baseline `9b90204` through `dd04cea`. This report records the
reproducibility substrate only; it does not claim benchmark truth, a pilot, or
an empirical result.

The M7 engineering checkpoint is complete after an independent review found
and the implementation closed trust-boundary blockers. The human M7 exit gate
remains open. The 24 records are explicitly screened candidates with
`human_approval: pending`, no immutable source commit, no verified license,
and no executable gold checks. They are therefore not executable benchmark
tasks and must not be counted as approved CapsuleBench evidence.

The frozen M7 plan is dated 2026-09-20 and this engineering record is dated
2026-09-22. The two-day execution variance is recorded here for auditability;
it does not change the frozen schedule or authorize a later module.

## Delivered artifacts

- `benchmark/schema.py` and `benchmark/loader.py`: strict frozen models,
  duplicate-key rejection, repository-lock digest checks, package path /
  symlink containment, immutable package snapshots with a digest over every
  package file, and loader provenance revalidation before scoring or execution.
- `benchmark/benchmark-manifest.json` and `benchmark/tasks/candidate-001`
  through `candidate-024`: 24 unique screening records across eight public
  repository URLs and two language labels. Every record is pending and
  non-executable; no generated label is treated as human truth.
- `baselines/budget.py` and `baselines/providers.py`: one neutral locked
  tokenizer/accounting path and the six common-interface conditions B0, B1,
  B2, B3, B4, and CC. P0 overflow, invalid encoding, path escape, budget
  mismatch, and untrusted artifact construction fail closed. Provider
  artifacts carry task, repository, package, and budget bindings.
- `experiments/models.py`, `preflight.py`, `run.py`, and `score.py`: strict
  config and JSONL replay models, immutable run IDs, append-only records,
  infrastructure-only retry links, unavailable-metadata receipts, dry-run
  default, live-agent preflight gating, condition-blind declared-check
  scoring, loader-root-bound scoring, and clean Git checkout attestation
  (origin, immutable commit, and clean status including ignored files) for live
  runs. Scoring executes checks in an isolated copy so runtime artifacts cannot
  mutate the authoritative task package.
- `experiments/configs/m7-screening.yaml`: engineering screening configuration
  with no model/version freeze and dry-run enabled.
- Focused integration tests in
  `tests/integration/test_benchmark_tasks.py`,
  `tests/integration/test_baseline_budget_parity.py`, and
  `tests/integration/test_experiment_replay.py`.

## Verification

The following commands were run against the implementation candidate:

| Check | Result |
|---|---|
| M7 focused integration suites | 53 passed |
| M6 adapter/MCP/vertical smoke suites | 13 passed |
| Full repository regression (`uv run pytest -q`) | 1126 passed in 304.33s |
| Ruff on M7 source and focused tests | passed |
| Mypy on `benchmark baselines experiments` | passed, 11 source files |
| `git diff --check` | passed after task-manifest EOF normalization |
| CCS-2.1 SHA-256 | `aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c` |
| Frozen execution-plan SHA-256 | `7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0` |

The full regression is a cumulative engineering check. It does not convert
the screening records into benchmark observations. The first benchmark-agent
delegation returned provider HTTP 429 and was not used as evidence; later
independent-review dispatches were also interrupted by 429. The work was
completed in the main working tree and every interruption is retained in the
AI-use ledger.

## Research and claim boundary

- C3 now has a strict package/manifest interface and negative tests for
  duplicate keys, unsafe paths, digest mismatch, approval boundaries, and
  condition-blind checks. It does not yet have 24 approved repositories,
  source commits, licenses, paired capsules, gold atoms/spans, executable
  target/invariant/spillover checks, or adjudication records.
- C4 has provider interfaces, a shared neutral budget, preflight receipts,
  replayable run records, and a scorer. No pilot or full run has started; no
  TER, PIP, BSR, token comparison, effect size, interval, p-value, or
  superiority claim is supported.
- C5 gains auditable source/test/governance artifacts. The human approval,
  second-reviewer (at least 25%), and model/version freeze requirements remain
  outstanding.
- RQ1--RQ4 remain unmeasured. Engineering test counts are not agent-task
  results.

## Known limitations and decisions required

1. Human authors must verify, approve, or exclude each candidate, bind every
   repository to an immutable commit and verified license, construct paired
   old/new capsules, and validate objective target, invariant, and spillover
   truth against source evidence.
2. A second independent reviewer must inspect at least 25% of approved tasks.
3. The author must freeze actual Codex/Claude model and version identifiers in
   an approved agent configuration before any pilot.
4. G2/pilot authorization is not present. No M8 pilot, M9 full experiment, or
   later module was started by this work.

The first independent read-only review of the pre-repair candidate returned
**BLOCK/changes required**. Its Critical/Important findings covered P0 label
sanitization, approval gating, duplicate JSON and package-root checks,
symlinked scorer paths, token-accounting forgery, preflight authentication and
metadata binding, retry classification, command exactness, and CC provenance.
The fixes are covered by new regression tests and the cumulative suite above.
Later review probes also drove fixes for loader provenance, artifact task and
budget binding, external scoring roots, mutable package content, parent
symlink aliases, runtime-cache injection, ignored live-workspace files, and
untrusted live workspaces. Independent review dispatches were intermittently
interrupted by provider HTTP 429; no result or benchmark observation was
substituted because of that interruption. The final implementation candidate is
`dd04cea`; an external final re-audit result was not available, so it is not
represented as a PASS and remains separate from the human exit decision.

## Frozen boundary

The frozen specification and execution plan were re-hashed during this module
and match their approved digests. No frozen file was edited. The M7 plan is
`docs/superpowers/plans/2026-09-20-m7-capsulebench-execution.md`.

**未开始下一模块。M8 has not started.**
