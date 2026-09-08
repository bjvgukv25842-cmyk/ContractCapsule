# M4-R1, M4-R2 and M4-R3 Remediation

Date: 2026-09-08. Status: **all three repairs implemented; independent technical
reaudit PASS; awaiting the author's separate M4 exit approval.** No M5 work.

## Authorization and Exact Commits

The author explicitly approved M4-R1, M4-R2 and M4-R3 and requested repair work.
Only those scopes from the preceding independent audit were implemented.
The durable approval record is decision M4-011; it truthfully records that the
instruction preceded the code and the written record was appended afterward.
No broader repair, frozen semantic change or module exit is inferred.

Worktree: `.worktrees/m4-exit-remediation`; branch: `codex/m4-exit-remediation`.
Branch point: `44585274b5fd639df6b76ea85825a007b01b1c48`, preserving the completed
audit archive while retaining byte-identical source/test/schema/dependency input
from audited technical `2ce1653`. The original M4 worktree remains at4458527;
the root worktree remains atc24696e. Neither is merged, reset or overwritten.

| Approved item | Technical commit | Change |
|---|---|---|
| M4-R1 | `19689c8e64ef818f9c31abc221a8ccf70bea85b4` | Require the exact admitted declaring owner for an explicit graph-source edge |
| M4-R2 | `e31a894` | Stable fixed-class optional allocation; retain rank order within each class |
| M4-R3 | `bb1d56daecbc31240b5ea1371378c50e63dd9c4b` | Reauthorize failed transactions and withhold invalidated public identity metadata |

The final independently audited technical candidate is exactbb1d56d above.
Subsequent governance-only commits do not silently change that audit target.

## Behavior and Compatibility

R1 prevents a denied occurrence of a shared atom from borrowing another
publication's admitted occurrence. The graph still honors genuinely admitted
shared owners, rejects foreign source declarations, preserves exact-release
capsule sources and uses consumer-owned dependency locks. Graph service and
configuration version are1.0.1, distinguishing the corrected interpretation.

R2 makes the compiler own P2-before-P3-before-P4 optional allocation regardless
of a replacement ranker's cross-class order. Stable sorting preserves relevance
order within each class. P0/P1 mandatory groups, dependency closure, matching,
FTS scores and full-text token accounting are unchanged.

R3 handles both explicit authorization failures and revocation coinciding with
another rank/budget/conflict failure. Public failure manifests omit capsule,
atom, provider, closure, conflict and expansion identities from an invalidated
snapshot. Request and permission digests use the existing unavailable zero
sentinel; only safe caller metadata and the compiler stamp remain.

`AUTHORIZATION_SNAPSHOT_INVALIDATED` counts prior admitted capsule snapshot
entries withheld, not the number individually revoked. Token total0/empty
sections under that marker mean **withheld**, not measured zero cost. The
internal selected/evidence/token transaction state remains intact. Ordinary
still-authorized P0/P1 budget failures continue to expose truthful attempts.
No new persistent sidecar or authorization infrastructure was introduced.

Actual output `manifest.compiler_version` and compiler service stamps are0.1.2.
The existing model/schema default0.1.0 remains unchanged for compatibility;
real compiler success and failure projections explicitly set the current
version. Old-version output expectations cannot silently replay as current.
All nine existing schemas, five public call shapes, core models, dependency
pins, tokenizer resources, M1 definitions and frozen files are unchanged.

Only five technical/test files differ from the repair baseline: graph.py,
session.py, manifest.py, plus the new test_graph_owner_admission.py and
test_m4_exit_repairs.py. There are no edits to the original745 test definitions.

## TDD and Verification

| Checkpoint | Actual controller evidence |
|---|---|
| Fresh repair-worktree baseline | 745 passed,31.49s |
| R1 RED | 4 genuine failures,2 positive controls pass |
| R1 GREEN | 6 new cases; combined64; full751 passed,30.50s |
| R2 corrected RED | 3 genuine failures,1 within-class positive control pass |
| R2 GREEN | 4 new cases; combined59; full755 passed,31.07s |
| R3 RED | 6 genuine failures,6 passes in combined repair file |
| R3 GREEN | 12 cases in combined file; combined67; full763 passed,33.14s |
| Final frozen four-file `uv run pytest ... -v` | 235 passed,16.69s |
| Formal fixtures | 30 passed |
| Ruff ordinary/no-ignore and all4 complexity rules in both modes | pass |
| Mypy /actual Python-file inventory | 72 source files /72 of72 in both scans |
| Offline lock /sdist+wheel /packaged compiler+tokenizer | pass;46 packages |
| B-zone schema regeneration /all existing schema and old test bytes | identical |

R2's first test run had four failures, but only its P2/P3 case reproduced the
production bug. Two P4 cases failed because the test's2030 as_of had expired
the default TTL, and the within-class fixture's1400 budget sat below one
single-atom rendering boundary. The tests were corrected before implementation:
the ranking-only P4 fixtures explicitly use the already-supported no-expiry
policy, and the within-class fixture uses1600. The three cross-class tests keep
a fixed1400 budget and do not search for the bug to establish their setup.
Original and corrected RED logs are both retained. Runtime TTL enforcement was
not changed or mocked away. No initial setup failure is counted as a fixed bug.

The new18 cases are6 R1 plus4 R2 plus8 R3. They are included in763, not added
to it. Original339 M3 nodes and all745 pre-repair nodes are retained. Focused,
full and formal populations overlap and are not independent research samples.

## Independent Reaudit

`m4_services_backlog_review` independently marked R1 PASS at19689c8:64 persistent
tests, the original denied-owner reproduction, and old-guard mutation with
4 failures/2 passes followed by a fresh6-case pass.

`m4_exit_independent_audit` independently marked the combined exactbb1d56d
candidate **PASS (technical)**. No unresolved finding was identified in the
authorized repairs and reviewed compiler interactions. This follows its prior
full M4 audit; it did not re-review unrelated unchanged modules from scratch.

Independent observations:18 new tests pass; frozen235 pass16.70s; full763
pass33.03s; formal30; static/type/complexity/inventory/lock/schema/build/resource
gates pass. The original two compiler diagnostics fail on old4458527 and pass
onbb1d56d; version/replay and four further failure-interaction checks pass.
Restoring the exact old R1/R2/R3 methods in isolated processes triggers4/3/6
real failures respectively. No source was mutated on disk. The reviewer
verified all165 tracked archive blobs remained unchanged and finished all
execution sessions before reporting.

Unmodified reports: `M4-2026-09-08-R1-reaudit.md` and
`M4-2026-09-08-remediation-reaudit.md`.
The80-file `M4-2026-09-08-remediation-evidence.tar.gz` preserves their raw logs,
scripts, manifests and the separately labeled controller RED/GREEN evidence.
SHA-256: `20e6cb48077c76dc475d6a861f6382ac4f47089ad7fc43b5e16251d447be714b`.
Every entry was checked against the internal SHA256.json after packaging;
source copies, caches, built packages, fixture databases and test private keys
are excluded. No failure log was rewritten to remove an unfavorable result.

## Research and Author Gate

The evidence supports C2 implementation and C5 reproducibility, with RQ1
allocation/metering and RQ2 trace/privacy engineering corrections. It is not
benchmark truth, C3/C4 evidence, TER/PIP/BSR measurement or cross-agent results.
No formal experiment, M5 activation/rollback, M6 adapter or schedule change.

Both frozen SHA-256 values still match:

- CCS-2.1: `aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c`.
- Plan: `7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0`.

Approved module progress remains4/12 (M0-M3,33.3%) until the author explicitly
approves M4's exit at the repaired exact candidate. Approval of repair IDs is
not that exit approval. G1/G2/G3 original dates are past and their unpassed
gates are not waived. After M4 approval, M5 planning and schedule/viability
decisions remain separately controlled. **M5 has not started.**
