# M7 Independent Review Record

Date: 2026-09-22 (Asia/Shanghai)

## First review

Scope: M7 candidate before the trust-boundary repair, compared with frozen
CCS-2.1, the execution plan, and the M7 implementation plan.

Verdict: **BLOCK / changes required**.

The reviewer reproduced these findings without changing the worktree:

1. P0 classification was inferred from source text and bypassed condition/gold
   sanitization, allowing labels to enter a runtime view.
2. Pending/unverified tasks could be scored, and a frozen manifest did not
   require approved executable locks.
3. Duplicate JSON keys were accepted in the manifest and repository lock, and
   a missing task-package root was silently accepted.
4. Declared scorer commands could follow symlinked scripts outside the task
   root and explicit commands could add undeclared arguments.
5. ContextArtifact token counts were caller-controlled.
6. Available preflight receipts were only self-hashed and did not fully bind
   adapter identity, model, version, or configuration.
7. Infrastructure retry eligibility could be spoofed with a task failure.
8. CC could fall back to full context and accept an unproven runtime view.

The findings were treated as blocking security/research-integrity issues, not
as evidence to be hidden or retried away. Fixes added strict approval gates,
metadata-only P0 declarations, locked token recomputation, duplicate-key and
package-root checks, realpath/symlink checks, exact command matching,
authenticated preflight receipts, retry consistency validation, and a strict
`CompiledView`/manifest binding for CC.

## Repair verification

Exact repair candidate: `39aa9c7` (base `9b90204`). The focused M7 suites pass
30 and the cumulative repository suite passes 1103. Ruff and Mypy pass for the
M7 implementation. The frozen CCS-2.1 and execution-plan digests remain exact.

## Follow-up repairs and final candidate

Follow-up probes found additional trust-boundary gaps: public task models were
not loader-attested, arbitrary context mappings could cross the run boundary,
scoring and live workspaces could be redirected, package contents could change
after load, and provider artifacts were not bound to task identity or budget.
These were repaired through commits `72c65eb`, `f677234`, `078bb63`, `bcb3c21`,
`9296c6e`, `3545acb`, and `dd04cea`, with negative regressions in the focused
suite. The final implementation candidate is `dd04cea`; the focused suites
pass 53 and the cumulative repository suite passes 1126 in 304.33 seconds.
The repairs additionally attest every package file, reject ignored live-workspace
files, and run declared scoring checks in an isolated package copy. Provider
HTTP 429 interruptions are retained as operational evidence and did not replace
any result. The final external re-audit dispatches were interrupted before a
verdict, so no independent PASS is claimed. This record does not approve
benchmark truth or authorize M8.
