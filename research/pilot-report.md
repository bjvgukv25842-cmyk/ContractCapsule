# M8 Pilot Readiness Report

Date: 2026-09-22 (Asia/Shanghai)

## Decision

The M8 engineering readiness gate executed and stopped at the G2 survival
decision. The checked-in pilot configuration is deliberately non-executable,
and the current CapsuleBench manifest is screening-only. The gate returned
exit status `2` with blockers; no adapter, network call, agent task, or pilot
observation was produced.

This is a readiness result, not a pilot result. It does not support TER, PIP,
BSR, an effect estimate, a cost comparison, or any empirical RQ conclusion.

## Frozen inputs

| Input | SHA-256 | Use |
|---|---|---|
| `docs/spec/CCS-2.1.md` | `aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c` | frozen semantics |
| `docs/superpowers/plans/2026-07-30-contract-capsule-fse-2027-execution-plan.md` | `7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0` | frozen module schedule |
| `research/protocol.md` | `d9b903f7ab66b7eff1cbdd8c7a554fe48edc05ba2158a3584db18606c6306df9` | author-approved G0 protocol |
| `benchmark/benchmark-manifest.json` | `3da2eee57a146412545aa4d0bfe9dad0685537d2f2492fc2fd68eda07feb428a` | observed screening manifest |

The first two frozen hashes match the values required by `AGENTS.md`. No
frozen specification, execution plan, or protocol file was edited.

## M7 residuals

The manifest contains 24 tasks with `status: screening`; all 24 have
`human_approval: pending`, `executable: false`, and
`repository.source_status: unverified`. There are zero immutable repository
commits, zero repository content digests, zero capsule digest pairs, and zero
tasks with complete target/invariant/spillover gold checks. The candidates
cover two language labels (21 Python and 3 Rust), not the protocol's minimum
of three ecosystems. The required adjudication ledger and frozen
Codex model/version/binary metadata are absent.

These are author-controlled benchmark-truth gaps, not infrastructure failures
to be hidden by retries. The earlier provider HTTP 429 interruptions in M7
review dispatches remain recorded as operational history; they were not
converted into an experiment result or used to replace an unfavorable result.

## Gate execution

The deterministic command was:

```text
uv run python -m experiments.pilot --config experiments/configs/m8-pilot.yaml --check --report .superpowers/sdd/2026-09-22-m8-pilot-execution/m8-readiness.json
```

The command wrote one JSON readiness report, returned `2` because the gate was
not ready, and did not create `results/pilot/runs.jsonl` or raw run output.
The schedule was exactly 48 cells: six tasks x four conditions (`B0`, `B2`,
`B4`, `CC`) x two repetitions. The checked-in config digest was
`sha256:7fc785ad7b8b69a4a826779a3fc0bd7a113fa5441c073e721f5dbd758eb43ae4`.

Observed blocker codes:

```text
manifest_digest_missing
protocol_digest_missing
benchmark_not_frozen
language_ecosystems_insufficient
task_not_approved
task_source_lock_missing
task_gold_checks_missing
task_capsule_digest_missing
adjudication_missing
g2_authorization_missing
agent_metadata_not_frozen
preflight_receipt_missing
pilot_not_enabled
```

The report writer uses exclusive creation and refuses to overwrite an existing
readiness report. The checked-in config has no model, version, or binary and
sets `dry_run: true` and `live_agent: false`; it cannot be mistaken for pilot
data. If a future receipt is supplied, signature verification also requires an
out-of-tree key via `--preflight-key`; the key is never persisted in the
repository or printed by the CLI.

## Required next decision

Before a later author-authorized M8 run, the human benchmark owners must
approve or exclude every candidate, bind approved repositories to immutable
commits and verified licenses, freeze paired capsules and executable gold
checks, complete the adjudication ledger with at least 25% independent second
review, freeze the actual Codex model/version/binary, produce an authenticated
preflight receipt, and authorize G2. Those inputs must be supplied as a new
versioned state; this report does not amend the frozen protocol or manufacture
them.

**M8 G2 is not passed. M9 has not started.**
