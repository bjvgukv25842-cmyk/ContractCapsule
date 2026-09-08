# M4 Three-Repair Independent Rereview

Date: 2026-09-08. Overall scoped verdict: **REQUEST CHANGES**.

Tested candidate: `2ce16535ece97733404e91715bb2b7586b54de20`.
Compared old source: `73f99aebe519e3b0857c9df5fbbeae99e06ff68c`.
Repair commit inspected: `ed7feaee6e2469a8e3d00873057fc433e79d8389`.
The four repair files are unchanged between repair and candidate commits.
Governance handoff read from the worktree at the supplied governance lineage
`cd6cfcf3c7385820862a341db01a6d440509f3bd`; no governance audit claim is made.

## Findings and Original Issue Status

### P1: Declaring atom ownership must also be currently admitted

Candidate location: `src/contractcapsule/resolve/graph.py:298`, `:309`, `:317`.
The narrow actionable range is 298-310, especially the global-owner check at309.

The original foreign-source attack is rejected after the repair, and capsule
source edges now stay with the declaring exact release. However, the repair
only checks that an atom source occurs somewhere in the declaring capsule's
full payload. It then checks whether that atom has ANY admitted owner globally,
not whether the declaring capsule is one of those admitted owners.

Independently reproduced with genuine publications and unchanged trusted local
services:

1. Capsule A (`com.example.policy`) contains approved atom `a`, scoped to
   `path:src/only.py`; its manifest permits `src/**`.
2. Capsule C (`com.example.second`) republishes the identical approved atom,
   but its manifest permits only `src/other/**`. Its graph declares
   `a -> absent`, mandatory requires. Neither capsule has dependency locks.
3. The task includes `src/only.py` and `src/other/file.py`. Both capsules pass
   capsule admission, but only A's atom passes the conjunction of atom and
   capsule scopes. Admission explicitly reports A `('a',)` and C `()`.
4. `graph.owners['a']` contains only A. Nevertheless C's graph edge is added
   through A's global atom node. `close_atoms({'a'})` fails
   `MISSING_DEPENDENCY`, rather than returning `{'a'}`.

Raw candidate output, independently produced in `variants.log`:

```text
variant admitted membership: [('com.example.policy', ('a',)), ('com.example.second', ())]
variant source owners: ['com.example.policy']
variant closure blocked by denied owner: MISSING_DEPENDENCY
```

The same residual behavior exists at the old target. This is a newly discovered
variant of the original ownership boundary, not a regression newly introduced
by the repair. It prevents closing the original graph finding completely.
The known original foreign-source examples themselves are now fixed.

This is not hostile arbitrary process execution, fabricated publication proof,
or an inconsistent policy callback. `ReusedApprovalFixture` reuses a genuine
approved atom, and both capsules use the real loader, permit, Registry and
EligibilityResolver. Only unpublished capsule scope/graph fields are authored.

Impact: graph obligations from an inadmissible source-owner pair influence
selected context and can spuriously block an otherwise valid admitted view.
The same global-owner branch processes conflicts, though this rereview stopped
after the concrete requires reproduction and does not claim a separately run
conflict variant. No unauthorized source text disclosure is claimed here.

Basis: CCS-2.1 sections 6/9/14.2, invariant5's pre-ranking scope boundary,
ADR-0004 per-member admission and rejected-member exclusion, and the original
task-4 requirement that individually denied sources contribute no selected edges.

Minimal proposed repair scope, subject to item-by-item author approval:
`resolve/graph.py` and focused regression tests only. After distinguishing the
declaring capsule-source case, accept an atom-source edge only when the exact
declaring CapsuleRef is in that atom's admitted owners. A known but denied
source should contribute no edge, consistent with existing denied-source
behavior. Preserve foreign-source rejection, exact-release capsule sources,
identical admitted owner handling and consumer-owned locks. No core schema,
Registry, policy, ADR, compiler, or M5 change is needed on current evidence.
No implementation was performed.

### Original Git locator/source-map finding: PASS, scoped

Candidate `compile/git_evidence.py:68-99` compares present approved source-map
fields with the exact evidence ID/mode/repository/revision/path/content digest
and locator fields, and validates a matching deterministic source anchor.
`compile/evidence.py:39` invokes it before extracting the span.

Genuine-publication tests for a substituted span and invented locator heading
fail at the old boundary and pass as safe rejections at the candidate. The
legacy anchor test also passes at the candidate. No new issue established in
this bounded repair review. Legacy test is a pure extraction/anchor diagnostic,
not evidence that an unbound legacy capsule can pass today's M3 publisher.

### Original Git lazy-fetch finding: PASS, scoped

Candidate `compile/git_evidence.py:23-50` sanitizes GIT_* environment, disables
lazy fetching and replacement objects, forbids transport, disables global/system
configuration, and applies a timeout. Lines53-65 route identity and both object
queries through that function. Registry.get was inspected: its read path
verifies stored publication data/CAS and does not invoke the publish-time M3
Git resolver. Therefore the previous unsafe M3 helper is not secretly reused
by this native runtime read path.

Real local partial clone: old boundary attempts `fetch origin`; candidate
raises EVIDENCE_UNAVAILABLE without that fetch and preserves all .git/objects
file bytes. Diagnostic transport prohibition prevented network even on old.
No remote request or third-party service was used; clone setup was local file://.
This is bounded evidence for the missing-promised-blob path, not an exhaustive
audit of every Git configuration or filesystem race.

## Independent Test Evidence

All runs used clean, reviewer-owned physical-path Git archives under this
directory. The old and candidate source trees were not edited. The installed
worktree Python executable supplied dependencies, but explicit PYTHONPATH selected
only the corresponding archive's src and tests. PYTHONDONTWRITEBYTECODE=1;
pytest cache disabled; fixtures/caches outside archived source. No uv sync,
dependency installation, repository/index/branch mutation or source repair.

### Persistent Candidate Pytest Run

Executed by this reviewer, not copied from author reports:

```text
candidate.log: exit0; 9 collected, 9 passed in1.77s
Python3.12.13; pytest9.1.1; Git2.50.1 (Apple Git-155)
```

Exact command recorded in candidate.log:

```bash
env PYTHONDONTWRITEBYTECODE=1 \
 PYTHONPATH=/private/tmp/m4-repair-rereview.XJYu96/candidate/src:/private/tmp/m4-repair-rereview.XJYu96/candidate \
 '/Users/litmus/Documents/Contract Capsule/.worktrees/m4-view-compiler/.venv/bin/python' \
 -m pytest -vv -p no:cacheprovider \
 --basetemp /private/tmp/m4-repair-rereview.XJYu96/pytest-candidate \
 tests/unit/test_service_review_regressions.py
```

CWD was `/private/tmp/m4-repair-rereview.XJYu96/candidate`. The runner also set
HYPOTHESIS_STORAGE_DIRECTORY outside source. Do not reuse an existing pytest
basetemp if its artifacts need preservation; choose a fresh scratch path.

### Old/Fixed Boundary Assertion Mapping

The diagnostic `variants.py` imports the candidate regression definitions and
invokes them against the chosen source archive with independent fresh fixtures.
This is NOT an old-revision pytest run: old source lacks the new regression file
and git_evidence module. For old only, a process-local import shim maps the new
legacy `validate_git_locator` symbol to old `_source_span`; it does not change
old production files or substitute policy/Registry code. Other eight assertions
invoke real old graph/native resolver paths unmodified.

All labels below map to `tests/unit/test_service_review_regressions.py`:

| Diagnostic label | Persistent node | Old boundary | Candidate |
| --- | --- | --- | --- |
| foreign-a-requires | test_foreign_graph_sources_cannot_rewrite_owner_dependencies[a-requires] | DID NOT RAISE | PASS |
| foreign-a-conflicts | test_foreign_graph_sources_cannot_rewrite_owner_dependencies[a-conflicts] | DID NOT RAISE | PASS |
| foreign-com.example.owner-requires | test_foreign_graph_sources_cannot_rewrite_owner_dependencies[com.example.owner-requires] | DID NOT RAISE | PASS |
| foreign-com.example.owner-conflicts | test_foreign_graph_sources_cannot_rewrite_owner_dependencies[com.example.owner-conflicts] | DID NOT RAISE | PASS |
| release | test_capsule_source_edges_are_bound_to_declaring_release | MISSING_DEPENDENCY | PASS |
| legacy-anchor | test_legacy_git_locator_still_requires_real_anchor | DID NOT RAISE, adapted old boundary | PASS |
| offline | test_missing_promised_git_object_never_starts_fetch | no-fetch assertion fails | PASS |
| different_span | test_git_excerpt_stays_bound_to_approval_and_stable_anchor[different_span] | DID NOT RAISE | PASS |
| locator_heading | test_git_excerpt_stays_bound_to_approval_and_stable_anchor[locator_heading] | DID NOT RAISE | PASS |

`old.log` records nine failed assertions; `variants.log` records nine passing
assertions. Both diagnostic runners exit0 because failures are captured and
printed for comparison. Exit0 does NOT mean the old implementation passed.
These direct invocations are additional executions of the same nine assertions,
not eighteen additional persistent tests. The denied-owner case is the sole
additional independently authored variant, run once per archive and reproduced
as problematic in both. It is not included in the 9-passed pytest count.

Original logs are preserved without replacement:

- candidate.log: actual candidate pytest output.
- old.log: old direct boundary assertions plus denied-owner diagnostic.
- variants.log: candidate direct assertions plus denied-owner diagnostic.
- old-offline/git-trace.txt: old fetch attempt, transport prohibited.
- variants-offline/git-trace.txt: candidate offline query trace.
- pytest-candidate/: persistent test fixtures including separate Git trace.

## Reproduction Files and Commands

`run_checks.py` is the runner used; `variants.py` is the executed comparison and
independent variant source. They create named fixture dirs, so their original
paths/logs should be preserved and any rerun should use a new copy/root.

For a fresh minimal rerun of the residual issue, the extracted standalone
`reproduce_denied_owner.py` creates a fresh directory on every execution:

```bash
env PYTHONDONTWRITEBYTECODE=1 \
 PYTHONPATH=/private/tmp/m4-repair-rereview.XJYu96/candidate/src:/private/tmp/m4-repair-rereview.XJYu96/candidate \
 '/Users/litmus/Documents/Contract Capsule/.worktrees/m4-view-compiler/.venv/bin/python' \
 /private/tmp/m4-repair-rereview.XJYu96/reproduce_denied_owner.py
```

This standalone file is a faithful extraction of the already executed variant,
with assertion exit semantics added for future use. It was not rerun after the
instruction to stop upon discovering a new finding; actual evidence is in the
executed `variants.py` output above. A fixed implementation should exit0 and
return {'a'}; current candidate would raise the explicit AssertionError.

## Baseline and Scope Record

Completely reread AGENTS, CCS-2.1, frozen execution plan, accepted ADR-0004,
M4-final-audit-handoff and M4-service-repairs. Both old/candidate archive frozen
digests match prescribed values:

- CCS-2.1: aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c
- frozen plan: 7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0
- AGENTS (root, old, candidate identical): 075362011bebbd15dff6febf706432dbf42dc09c77768508b5ec84c2d1fe46e5

Used code-review-and-quality guidance. Full compiler, full suite, formal tests,
lint/typecheck, packaging and governance integrity belong to the separate
reviewer. Their runs and author-reported 745 tests are not claimed here.
Read-only repair audit only; no subagents, network, fixes, author gate approval,
M4 exit approval, M5, formal experiment or schedule change. Original M4 end
date2026-08-21 is18days before this audit date; no gate was relaxed.
