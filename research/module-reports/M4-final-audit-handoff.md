# M4 Independent Exit Audit Handoff

Status: pending independent execution, not a review approval.

## Exact Targets

- Repository: `/Users/litmus/Documents/Contract Capsule`.
- Working branch: `codex/m4-view-compiler`.
- Approved M3 baseline: `4dbf4849c6e125d1cb5ac8d813e4aeb5dc75694d`.
- Technical candidate: `2ce16535ece97733404e91715bb2b7586b54de20`.
- Prior independent service review: `4bed753..73f99ae`.
- Service repair: `ed7feae`; compiler integration: `ccabe4e`.
- Schema inventory adaptation: `2ce1653`.

Read complete AGENTS, CCS-2.1, frozen execution plan, accepted ADR-0004 and the
derived M4 execution plan before auditing. Verify the two approved hashes.
Review read-only in a clean archive of the exact commit. Use resolved physical
paths on macOS (not `/tmp` aliases) and put caches outside the audited source.
Do not alter the branch, governance records, index or source while reviewing.

## Required Review

1. Reproduce each finding in `M4-services-independent-review.md` at its original
   target and verify its correction at the candidate. Check foreign atom and
   capsule graph-source ownership, exact release ownership, approved Git locator
   bindings, stable anchors, and no lazy-fetch subprocess or object-cache writes.
2. Review compiler composition independently of authoring-agent reports: strict
   raw input, genuine Registry trust, admission-before-coverage-before-ranking,
   native evidence bindings, deterministic ordering, double closure, SemVer
   provider locks, all mandatory P0/P1 and whole-provider preservation.
3. Check actual complete-text budget, optional groups, invalid empty content,
   stable safe blocker codes, no rejected-object identity leakage, late evidence
   revocation/drift and permission rechecks, selected witnesses, full decision
   coverage, service/resource locking and replay under current permissions.
4. Run the exact frozen four-file `uv run pytest ... -v`, full suite, formal
   fixtures, Ruff and all four complexity rules with/without gitignore; compare
   actual Python discovery against filesystem inventory. Run full Mypy, offline
   lock, Schema generation, original339 node preservation, protected-file hashes,
   ledger parsing, build/resource smoke and whitespace checks.
5. Run fault injection against the actual safety assertions. Existing six
   controller probes/logs are inputs to inspect, not independent review evidence.
   Add bounded external diagnostics when needed without changing audited source.

## Reporting

Return explicit PASS or REQUEST CHANGES with file/line evidence, reproducer,
severity, command exits and limitations. Distinguish tests run from code merely
inspected. Do not call a same-author rerun an independent audit. Do not waive
review findings based solely on the 745 passing tests.

Governance/report-only descendants may be checked separately for append-only AI
ledger, honest result counts and frozen boundaries. M4 author approval is still
required even after technical PASS. No M5, merge/push, schedule revision or formal
experiment is authorized by this handoff.
