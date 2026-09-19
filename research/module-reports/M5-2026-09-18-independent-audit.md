# M5 Independent Exit Audit

Date: 2026-09-18

Reviewer: native read-only agent `m5_final_audit`

Target: exact commit `3de72974afd0f42cfe1d2f932ee9a17645780eea` in an isolated
copy of `codex/m5-validation-swap`. The reviewer made no source or test edits.

## Verdict

**PASS.** M5-5, M5-6, and M5-7 have no unresolved blocking finding.

## Scope Checked

- runtime scope/action/ticket/receipt/audit integrity and additive migration;
- serialized action boundary, UNCERTAIN reconciliation, generation/CAS checks;
- ticket one-time use, request/operation binding, expiry and direct-row tamper;
- prepared evidence authentication and Registry/runtime identity binding;
- transaction-time activation and rollback authorization;
- high/critical independent activation approval and execution-approval
  separation;
- audit-failure atomicity, restart replay, expiry/revocation replay, and
  stale/foreign receipt rejection;
- M5-4B Git replacement-ref resistance and Docker resource-failure
  persistence/replay;
- M5-7 real deterministic Docker reference path through validation, activation,
  restart, and rollback;
- final source/test inventory, frozen hashes, lock, build, lint, type, and
  complexity gates.

## Finding Closure

The only finding in the final audit cycle was M5-F1/P1 in prior candidate
`5ccceab`: lexical RFC3339 comparison allowed a fractional current timestamp to
pass a valid no-fraction expiry. The finding was reproduced as an actual
activation, not merely a unit-level speculation. Commit `3de7297` parses
aware UTC datetimes in the runtime store and approval verifier. Three new
regressions fail on the old implementation and pass on the repair:

1. boundary-ticket expiry;
2. prepared activation expiry;
3. activation-approval issued/expiry boundary.

The reviewer reran the exact final candidate and confirmed all three, then
returned PASS. Earlier M5-4B REQUEST CHANGES and all negative/failure evidence
remain preserved in their original reports.

## Reproduced Results

- Exact expiry regressions: 3 passed.
- Frozen security tests plus M5-7 path: 15 passed.
- M5-4B twin regression set: 24 passed.
- Full suite: 1047 passed.
- Ruff, complexity rules in both discovery modes, Mypy, hashes, protected
  files, lock, and whitespace checks: passed.

This is an independent engineering audit, not a human benchmark adjudication,
formal experiment, or claim of cross-agent superiority.
