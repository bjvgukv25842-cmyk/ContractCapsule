# M8 Pilot Readiness and Survival Gate

Date: 2026-09-22 (Asia/Shanghai)

## Authorized scope and completion

The user authorized planning and execution of M8, with rapid closure of any
blocking M7 residue and no expansion into M9. The implementation followed the
dated plan `docs/superpowers/plans/2026-09-22-m8-pilot-execution.md` and stopped
at the G2 survival gate. M8 engineering execution is complete for the
readiness path; the empirical pilot is intentionally not authorized by the
current inputs.

The implementation commits are `ec731da` (configuration and CLI) and
`41f340e` (preflight receipt integrity hardening). Governance artifacts are
recorded in the commit that contains this report.

## Changes

- `experiments/pilot.py` adds strict, immutable pilot configuration models,
  deterministic six-task/condition/repetition scheduling, digest-bound
  manifest and protocol checks, loader-backed task checks, preflight receipt
  integrity/identity checks, and structured fail-closed blocker codes.
- `experiments/configs/m8-pilot.yaml` declares the exact 48-cell scope but is
  explicitly non-executable (`dry_run: true`, `live_agent: false`, and no
  model/version/binary).
- `results/pilot/.gitkeep` establishes the output boundary without creating
  pilot data.
- `tests/integration/test_pilot_gate.py` covers scope cardinality, digest
  binding, screening-task refusal, deterministic scheduling, checked-in config
  refusal, no-run-record behavior, and non-overwrite protection.
- `research/pilot-report.md`, this report, the decision log, claim matrix, and
  AI-use ledger preserve the G2 decision and the absence of observations.

## Verification

| Command | Result |
|---|---|
| `uv run pytest tests/integration/test_pilot_gate.py -q` | 10 passed |
| `uv run ruff check experiments/pilot.py tests/integration/test_pilot_gate.py` | passed |
| `uv run mypy experiments/pilot.py` | passed |
| `uv run python -m experiments.pilot --config experiments/configs/m8-pilot.yaml --check --report .superpowers/sdd/2026-09-22-m8-pilot-execution/m8-readiness.json` | exit 2, expected fail-closed refusal |
| JSON inspection of the readiness report | valid JSON; `ready: false`; 48 scheduled cells |
| run-output inspection | no `results/pilot/runs.jsonl`; no raw run output |

The M7 residual regression evidence remains the prior exact candidate's
`1126 passed` full suite plus 53 focused M7 tests and 13 M6 smoke tests. The
M8 focused gate suite passed 10 tests. The final cumulative regression after
the governance-ledger correction passed `1136 tests in 314.92s`; the first
attempt (1135 passed, one ledger-enum failure) is retained as a genuine
verification failure and was fixed without changing any experiment data.

## Research boundary

| Area | Evidence added | Claim still unavailable |
|---|---|---|
| C1 | Atomic, fail-closed readiness boundary before an adapter call | behavioral replacement result |
| C2 | deterministic config, digest checks, and 48-cell schedule | live-agent vertical pilot |
| C3 | explicit refusal of screening candidates and missing adjudication | approved benchmark truth, gold checks, second-review agreement |
| C4 | preregistered pilot shape and auditable refusal report | any pilot observation, TER/PIP/BSR, cost, effect, or RQ result |
| C5 | versioned report, hashes, tests, and AI-use record | external replication and submission audit |

No new observation was generated. No retry, provider outage, or external
condition was used to replace a valid result. The prior M7 HTTP 429 events are
retained as operational limitations only.

A separate read-only M8 audit was requested but interrupted before a verdict;
no independent PASS is inferred from that attempt. The local focused and
cumulative regressions above are the available engineering verification.

## Frozen hashes and decisions

- CCS-2.1: `aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c`
- Frozen execution plan: `7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0`
- Author-approved protocol: `d9b903f7ab66b7eff1cbdd8c7a554fe48edc05ba2158a3584db18606c6306df9`

The human benchmark and G2 decisions remain open. **M9 was not started.**
未开始下一模块。
