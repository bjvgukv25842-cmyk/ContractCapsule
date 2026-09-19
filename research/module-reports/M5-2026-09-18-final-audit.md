# M5 Final Technical Audit and Exit Record

Date: 2026-09-18 (Asia/Shanghai)

## Scope

This record closes the remaining M5-5 runtime-store work, M5-6 atomic
activation/rollback work, and the M5-7 integrated reference path. It supplements
the historical M5 reports and does not rewrite any earlier failure, review, or
recovery record.

The exact technical candidate is `3de72974afd0f42cfe1d2f932ee9a17645780eea`
on branch `codex/m5-validation-swap`. The candidate includes the approved M5-4B
regressions, the runtime store and boundary, guarded activation and rollback,
the integrated reference task, and the RFC3339 expiry repair. The worktree was
clean at audit completion.

## Delivered Behavior

- C-zone runtime state is isolated by tenant, principal, repository,
  environment, and session, with authenticated state/action/ticket rows.
- Initialization requires a validated generation-zero binding. Actions are
  serialized and retain RUNNING/UNCERTAIN state until explicit completion or
  reconciliation; leases and client disappearance are not treated as proof of
  termination.
- Boundary tickets are signed, scoped, generation- and action-epoch-bound,
  single-use records. Direct database resets are detected by a row signature.
- Prepared replacements are authenticated and bound to the request, old/new
  binding, evidence payload, operation, and expiry. There is no unconditional
  pointer setter.
- Activation performs transaction-time validation and approval checks, then
  atomically updates the active pointer, consumes the ticket, writes the receipt,
  and writes the critical audit event. Failure rolls back the complete
  transaction; a committed operation can be replayed from its durable receipt.
- High/critical or explicitly approval-required activation needs a distinct
  activation-domain approval. An execution approval cannot substitute for it.
- Rollback requires a current matching generation, a valid source receipt, a
  fresh boundary, and transaction-time rollback authorization. It restores the
  old binding at a new generation and is idempotent after commit.
- RFC3339 timestamps are parsed as UTC-aware datetimes before all prepared,
  ticket, and approval expiry comparisons. Exact no-fraction timestamps are
  covered by regression tests.
- The M5-7 integration test executes a real deterministic Docker twin, binds
  its authenticated evidence into a prepared replacement, activates it,
  restarts the state owner, verifies durable replay, and rolls back.

## Independent Review

The native read-only reviewer `m5_final_audit` audited the exact final commit in
an independent copy. The first review identified M5-F1 (P1): lexical comparison
of valid RFC3339 timestamps could accept an operation briefly after an exact
no-fraction expiry. The finding was reproduced against activation, then fixed
in `3de7297` with three RED-to-GREEN regressions covering tickets, prepared
activation, and activation approval. The final independent verdict is **PASS**;
no unresolved blocking finding remains.

The previously closed M5-4B findings remain covered by the real replacement-ref
and Docker timeout/output-limit persistence/replay regressions. Historical
REQUEST CHANGES reports and their failing evidence remain intact in the earlier
M5-4B records.

## Verification

| Check | Result |
|---|---|
| Frozen security command (`tests/integration/test_replacement.py` and `tests/security/test_fail_closed.py`) | 14 passed |
| Frozen security command plus M5-7 integrated path | 15 passed |
| M5-4B twin replacement/resource regression set | 24 passed |
| Exact RFC3339 expiry regressions | 3 passed |
| Full repository regression | 1047 passed |
| Formal fixtures, schema parity, ledger, frozen-baseline tests | 150 passed |
| Ruff default and `--no-respect-gitignore` | passed |
| C901/PLR0911/PLR0912/PLR0915 default and no-ignore scans | passed |
| Mypy | 71 source files, passed |
| Actual Python inventory vs Ruff discovery | 118 / 118 / 118 |
| `uv lock --check --offline` | passed, 46 packages |
| Offline sdist and wheel build plus isolated wheel import smoke | passed |
| Frozen CCS-2.1 SHA-256 | `aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c` |
| Frozen execution-plan SHA-256 | `7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0` |
| Accepted ADR-0005 SHA-256 | `c4457f5da29903261ea7ce58c68e28c43cbdfb74eb55e70a8ff5c1d1617921a0` |
| Protected-file and `git diff --check` verification | passed |

The full suite and Docker fixture are engineering evidence only. No benchmark
ground truth, cross-agent superiority, or formal RQ3 result is claimed. Failed
attempts, the initial M5-4B REQUEST CHANGES, and the M5-F1 reproduction remain
auditable rather than being replaced by the passing reruns.

## Commit Map

- `1301a15` — approved M5-4B replacement-ref and resource-failure regressions.
- `768e337` — authenticated runtime store and safe boundary.
- `0fdc7c9` — guarded atomic activation, receipts, and rollback.
- `5ccceab` — behavior-preserving migration/complexity split.
- `a7c7caf` — integrated validation-to-activation/rollback regression.
- `3de7297` — timestamp parsing repair and exact expiry regressions.

## Exit State

M5-5, M5-6, and M5-7 have technical PASS and an independent PASS. The
author's module-exit decision is recorded separately from the engineering
evidence; no M6 implementation or formal experiment is counted in this report.
The original G1/G2/G3 dates remain missed and were not backfilled.

**M5 technical work is complete. M6 has not started.**
