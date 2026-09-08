# M4 Independent Exit Audit: Consolidated Result

Date: 2026-09-08. Verdict: **REQUEST CHANGES**. M4 is not formally complete.
The authorized audit and evidence archive are complete; all code repairs require
the author's separate item-by-item approval. No M5 work has started.

## Audited Identities and Independence

- Technical candidate: `2ce16535ece97733404e91715bb2b7586b54de20`.
- Governance candidate: `cd6cfcf3c7385820862a341db01a6d440509f3bd`.
- Approved M3 baseline: `4dbf4849c6e125d1cb5ac8d813e4aeb5dc75694d`.
- Existing repair: `ed7feaee6e2469a8e3d00873057fc433e79d8389`.
- Scoped reviewer: `m4_services_backlog_review`, not a repair implementer.
- Full reviewer: `m4_exit_independent_audit`, fresh context, not an implementer.

Native internal agent dispatch was rechecked and worked. A provider429 briefly
interrupted the full reviewer; the same reviewer resumed existing artifacts,
without restarting completed checks or replacing unfavorable results. Both
reviewers finished and reported all execution sessions ended. The previous
dispatch-unavailable blocker is historical, not the current reason for stopping.

Reviewers used separate physical-path Git archives and the locked dependency
runtime with explicit archive-first imports, offline mode and caches outside
source. The full reviewer verified all124 archived tracked Git blobs unchanged
and all94 recorded source/test/schema/resource hashes matching the candidate.
Root and M4 worktrees were clean and unchanged throughout independent audit.
Only this subsequent governance archive changes the M4 branch; no production
source, test, schema, dependency, frozen input or repair branch is changed.

## Findings and Repair Authorization Requests

The following stable IDs are used for author approval. Risk labels P1/P2 in
this table are review severities, distinct from atom compression classes.

| Approval ID | Severity | Finding | Source review |
|---|---|---|---|
| M4-R1 | P1 | Explicit graph source must belong to the exact currently admitted declaring owner | services rereview, residual graph finding |
| M4-R2 | P2 | Optional budget allocation accepts cross-class reordering from a replacement ranker | full audit IA-M4-01 |
| M4-R3 | P2 | Late revocation returns now-denied identities through the stale failure manifest | full audit IA-M4-02 |

### M4-R1: Admitted Graph Declaration Ownership

Location: `src/contractcapsule/resolve/graph.py:298`, especially line309.
Two genuine publications contain the same approved atom. Only A's occurrence
passes the conjunction of task/atom/capsule scopes; C's admitted atom set is
empty. C nevertheless adds an explicit `a -> absent` dependency through A's
global atom node. Selecting A's `a` incorrectly raises MISSING_DEPENDENCY.
This is a residual form of the original ownership defect, not evidence that
the repair introduced it. No unauthorized source-text disclosure is claimed.

Requested repair: only the graph ownership check and focused tests. Require
the declaring exact CapsuleRef to be among the atom's admitted owners before
importing an atom-source edge. Skip a known but denied source occurrence;
retain foreign-source rejection, exact-release capsule sources, allowed shared
owners and consumer-owned locks. Test denied-owner requires/conflicts, positive
shared-owner cases and the public compile path. No schema or policy change.

### M4-R2: Fixed Compression-Class Allocation

Location: `src/contractcapsule/compile/session.py:317`.
A replacement ranker returns identical real FTS5 atoms, scores and matches,
but reverses their order. At a1400-token budget, native ranking selects P2,
the alternate selects P3, and both views are valid. Native FTS5 itself remains
correct; the gap is the replaceable-service/compiler boundary.

Requested repair: make the compiler partition optional assembly in fixed
P2 then P3 then P4 order, preserving rank order within each class. Keep P0/P1
mandatory stages, full-closure grouping, actual text accounting and FTS scores
unchanged. Add fixed-budget reversed-ranker regression and same-class ordering
coverage; use the observed failure as RED, not a search loop that requires the
bug to remain present. No public protocol or dependency expansion.

### M4-R3: Current-Authorization Failure Projection

Locations: `src/contractcapsule/compile/manifest.py:34`, `:43`, `:107`;
`src/contractcapsule/compile/session.py:396` and `:401`.
Revocation after the final native read correctly yields POLICY_SNAPSHOT_CHANGED,
invalid validation, empty body and no handles. The returned manifest still
contains the previously admitted capsule/atom IDs and old authorization digest.
The issue is stale authorized metadata after revocation, not previously
never-authorized original text or unsafe activation.

Requested repair: on authorization/snapshot invalidation, return an aggregate-
only public failure projection without old graph/capsule/atom/provider/conflict
identities. Use safe unavailable authorization metadata rather than representing
the old snapshot as current. Keep truthful attempted decisions and token totals
for ordinary still-authorized budget failures. Do not add a new sidecar or erase
existing internal audit evidence. Add late-revocation tests across all returned
identifier-bearing fields, including partial revocation and unchanged-grant
positive cases. Preserve the public model/schema shape.

All three block the currently adopted acceptance requirements. No item is
approved by this report. Do not implement even a small fix until the author
names the approved IDs. If actual repair needs a new public interface, core
semantics or dependency, stop for a separate ADR/approval.

## Fresh Verification and Limitations

| Population/check | Independently observed result |
|---|---|
| Existing service-repair regression file | 9 passed in1.77s |
| Frozen four-file M4 command, exact argv with `uv run ... -v` | 235 passed in16.53s |
| Full committed suite | 745 passed in29.77s |
| Formal fixtures | 30 passed |
| Full reviewer additional boundary suite | final2 failed,9 passed in5.60s |
| Scoped denied-owner diagnostic | reproduces failure in old and candidate source; not a persistent test |
| Fault injection | 8 independent safety mutations plus2 persistent ADR mutations caught by target assertions |
| Ruff and four complexity rules, ordinary/no-ignore | all pass; actual70/70 Python files in archive and worktree |
| Mypy /offline lock | 70 source files /46 packages, pass |
| B-zone and eight core Schema checks /wheel+sdist+offline resource smoke | pass |
| Independent governance tests | 77 passed |
| Original339 node retention /frozen and core identity /ledger provenance | pass |

The nine service tests,235 frozen tests and30 formal fixtures overlap the745
suite; they are not added to it. The11 additional compiler diagnostics are not
committed product tests. The initial10-case run had2 failures/8 passes; adding
one external-drift case produced the final population without discarding either
failure. Old service checks were direct invocations, not an old pytest suite;
the legacy-only helper used a disclosed import shim. Detailed original reports
preserve those distinctions.

The controller separately confirmed all three findings through the reviewer
reproducers, with actual AssertionErrors rather than setup/import errors. Those
confirmations are not counted as additional independent reviews. Controller
governance checks also passed77 tests and verified logs/hashes; independent
governance conclusions come from the full reviewer, not the authoring controller.

## Evidence and Research Boundary

Unmodified reviewer reports:

- `M4-2026-09-08-services-rereview.md`.
- `M4-2026-09-08-compiler-audit.md`.

`M4-2026-09-08-audit-evidence.tar.gz` contains65 files: reviewer reports, exact
commands/logs, diagnostic/mutation scripts and hashes, plus separately labeled
controller confirmations. SHA-256:
`8d34ce3cdd4c749b18524bade071ee29e8e53848c6d88a69e698b01cdfc0e491`.
All entries were verified after archive creation against SHA256.json. No source
snapshot, environment/cache, test fixture database or test private key is exported.
Raw logs are losslessly archived, including expected assertion failures.

This adds C2/C5 engineering review evidence and identifies RQ1 selection and RQ2
trace/privacy implementation defects. It does not establish C3/C4, empirical
RQ1-RQ4 results, TER/PIP/BSR, or completion of the M5/M6 vertical slice.
Model usage and billed costs were not exposed and are not invented in the ledger.

Both frozen SHA-256 values remain unchanged:

- CCS-2.1: `aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c`.
- Plan: `7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0`.

M0-M3 remain the four author-approved modules (4/12,33.3%). G1/G2/G3 original
dates have passed without all gates being satisfied. No gate or schedule is
rewritten. After approved repairs, independently audit the exact repaired
candidate, then request M4 author exit. **No merge/push, formal experiment or M5.**
