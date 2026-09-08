# Independent M4 Repair And Integrated Exit Reaudit

Verdict: **PASS (technical)** for `bb1d56daecbc31240b5ea1371378c50e63dd9c4b`.
Date: 2026-09-08, Asia/Shanghai. Reviewer: `m4_exit_independent_audit`.
Pre-repair baseline: `44585274b5fd639df6b76ea85825a007b01b1c48`, technically identical to prior audited `2ce16535ece97733404e91715bb2b7586b54de20`.
Approved M3: `4dbf4849c6e125d1cb5ac8d813e4aeb5dc75694d`.

No unresolved finding was identified in the authorized R1-R3 repair scope or reviewed compiler interactions. This reviewer did not implement these repairs. This result supersedes the open technical findings for this exact repaired candidate, not the historical REQUEST CHANGES verdict for the old candidate. It is **not M4 author exit approval**, a merge instruction, an experiment result, or authorization to start M5.

## Finding Disposition

### M4-R1: Declaring-owner admission (original P1) - Addressed

`src/contractcapsule/resolve/graph.py:309` now requires the exact declaring capsule reference to be among the source node's admitted owners before importing that declaration. Full-payload membership alone, or another capsule's admitted occurrence of an identical atom, no longer supplies authority. Capsule-source handling remains pinned to its declaring release; admissible shared-owner requires/conflicts remain effective.

Independently reran all six new owner tests, including missing requires and self-conflict forms through graph and complete compiler paths. Restoring the exact old `explicit` method in memory produces **4 failed, 2 passed**; the repaired candidate passes all six. This independently verifies the guard rather than merely accepting the separate scoped review's PASS.

Graph runtime version and configuration digest both advance to `1.0.1`. No core graph schema or published capsule data changes.

### M4-R2: Fixed compression-class allocation (IA-M4-01, original P2) - Addressed

`src/contractcapsule/compile/session.py:318` uses stable class sorting before optional assembly. P0/P1 remain mandatory earlier stages. The valid fixed class names order P2 before P3 before P4; stable sorting retains the replacement ranker's relative order within a class. It does not rewrite relevance scores, matched values, atoms, or closure membership.

The original independent diagnostic was adapted only by replacing its search-for-a-bug setup with the known **1,400-token budget**. On the old candidate it still fails its actual selection assertion. On this candidate the native and reversed rankers both return a valid view selecting `p2`, excluding `p3`. The new persistent tests cover all three P2/P3/P4 pairings and preserve within-class rank order. Restoring the exact old `_select` method produces **3 failed, 1 passed** among these four tests.

The native FTS ranker's existing class-first ordering remains unchanged; the policy is now also enforced at the compiler's replaceable-service boundary.

### M4-R3: Current-authorized failure projection (IA-M4-02, original P2) - Addressed

`src/contractcapsule/compile/session.py:402` redacts explicit authorization/snapshot invalidation failures. Other failures call `_admission_is_current` at line 417; a changed request, changed admission, or reauthorization exception cannot export the old snapshot. `src/contractcapsule/compile/manifest.py:139` constructs the withheld public projection without clearing the internal transaction.

The original late-revocation diagnostic now returns empty content/handles, empty capsules/decisions/providers/closure/conflicts/expansions, zeroed permission and request digests, only the stable compiler service stamp, and `AUTHORIZATION_SNAPSHOT_INVALIDATED: 1`. No private capsule/atom identifiers survive. It still fails on the old candidate.

Persistent coverage independently passes full, partial and malformed permission changes, unchanged permission equality, revocation combined with rank/budget/conflict failures, and still-authorized budget attempts. Restoring the exact old `failure` method produces **6 failed, 6 passed** in the combined 12-case repair file. Four further independent checks pass: revocation at replay comparison, reauthorization failure with a raw private error, authorized P1 overflow retaining actual token attempts, and preservation of internal selected/evidence/token state during public redaction.

The withheld count is the number of prior admitted capsule snapshot records suppressed, **not the number individually revoked**. Public `tokens.total=0` with the invalidation marker means token details are withheld, **not zero actual cost**. Internal attempted counts remain present, and ordinary still-authorized P0/P1 budget failures preserve truthful counts and decisions. Downstream research consumers must honor this documented distinction.

## Versions, Replay And Boundaries

The emitted `manifest.compiler_version` and compiler service stamp both explicitly report `0.1.2`; graph reports `1.0.1`. Current manifest schema validation passes. Same request/current services/current permissions reproduces identical output; an expectation with old compiler-version identity fails `REPLAY_MISMATCH` with no content. Revocation while forming that failure also produces the withheld projection.

All nine existing schema files, including the B-zone schema, are unchanged. Leaving the existing runtime model/schema default at `0.1.0` does not mislabel actual compiler output because both success and withheld construction explicitly set the current version. The five public call shapes, core models, dependencies and frozen semantics remain unchanged.

## Independent Verification

All executions used this reviewer's new physical Git archives at `/private/tmp/cc-m4-repair-independent-sABc2vmV`. Product and helper imports were explicitly verified to point into `candidate/`, never the source worktree or a `/tmp` alias. The existing locked `.venv` supplies dependencies only. `UV_NO_SYNC=1`, `UV_OFFLINE=1`, disabled pytest cache, and external cache paths prevent source/environment synchronization writes.

| Check | Independent result |
|---|---|
| New persistent R1-R3 tests | 18 passed, 4.34s |
| Original two diagnostics plus version/replay check | 3 passed, 2.57s |
| Same two adapted diagnostics on old candidate | 2 expected assertion failures, not setup/import errors |
| Additional failure interaction checks | 4 passed, 0.99s |
| Exact frozen four-file `uv run pytest ... -v` | 235 passed, 16.70s |
| Full Pytest | 763 passed, 33.03s |
| Formal fixtures | 30 passed |
| Ruff ordinary and no-ignore | both exit 0 |
| C901, PLR0911, PLR0912, PLR0915 ordinary and no-ignore | both exit 0 |
| Actual scanned-file inventory | 72/72 in archive and worktree, both ignore modes |
| Full Mypy | 72 source files, exit 0 |
| Offline lock check | 46 packages, exit 0 |
| B-zone schema regeneration | byte-identical |
| Eight A-zone schemas | unchanged M3 bytes; identical regenerated structured schemas |
| Offline sdist/wheel build | exit 0 |
| Extracted-wheel import and local tokenizer smoke | exit 0; packaged product import; `hello world` = 2 tokens |
| Scope and whitespace diff | five approved implementation/test files only; whitespace exit 0 |
| Test-node preservation | 339 subset of 745 subset of 763; no missing old nodes; 18 new persistent nodes |
| Archive identity after checks/mutations | all 165 tracked Git blobs unchanged |

The 18 new tests are included in the 763 total; the 235 and 30 populations also overlap with the full suite. Mutants are expected failed verification runs, not additional defects in the repaired code or experimental observations.

Mutation execution parsed the exact pre-repair source method from the old archive and installed that method in a disposable process against the current classes. It did not edit, revert or patch an audited source file. All three mutations reached behavioral failures, including actual output assertions. Every log is preserved, and the runner refuses to overwrite a completed log label.

## Inputs And Governance Separation

Fully reread AGENTS, CCS-2.1 and the frozen execution plan; used the prior full review context, accepted ADR-0004/derived plan and exact historical findings to focus the present review on the five-file change and shared interactions. Both frozen SHA-256 values match:

- CCS-2.1: `aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c`.
- Frozen execution plan: `7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0`.

Read the controller's supplementary, uncommitted M4-011 decision entry and last AI-use row. They explicitly record prior user approval for R1-R3, the later timestamp of the durable record, corrected R2 fixture assumptions, withheld-count/token interpretation, and pending M4 author exit. These later governance records are not silently included in the audited technical SHA. Their final archival completion remains the controller's separate responsibility.

During final read-only observation, worktree HEAD remained `bb1d56d`; only `research/decision-log.md` and `research/ai-usage-ledger.jsonl` were modified by the controller. This reviewer did not write source, tests in the repository, governance, index, branch, lock or dependency files, and did not create subagents or invoke external plugins, model CLIs or network services.

## Limitations And Exit

This is a bounded integrated repair/exit reaudit built on the prior full independent M4 review. The three source changes and both new test files were inspected, with full fresh regression and targeted falsification; unchanged unrelated modules were not re-reviewed from scratch. No new runtime feature, adapter, activation protocol, empirical benchmark, online dependency advisory scan, or arbitrary hostile-Python sandbox was added or claimed.

The external diagnostic pytest rootdir is the parent temporary directory; verified source-first imports still bind it to the exact candidate. Synthetic Registry/M3 fixture publications are real approval-backed test publications, not human benchmark truth. Prior reports' historical RED corrections are disclosed, not newly recreated here; this reaudit had no corrected setup/import failures. Model usage and billed cost are not exposed and are not invented.

The frozen M4 end date was 2026-08-21, 18 days before this task date. PASS here does not waive G1/G2/G3 or any remaining module/author gate. R1, R2 and R3 can be marked technically addressed for this exact candidate; the author must separately decide the M4 exit. **M5 has not started.**

## Minimal Export

`artifact-manifest.json` lists the exact small evidence set: this report; `run_audit.py`, `supplemental.py`, `mutate_repair.py`, `make_export_manifest.py`; `probes/test_prior_findings.py`, `probes/test_failure_interactions.py`; `commands.jsonl`, `checks.json`, `node-retention.json`; and `logs/*.log`. Do not archive source copies, caches, distributions, extracted wheels, generated fixture directories, or test private keys. Paths are relative to `/private/tmp/cc-m4-repair-independent-sABc2vmV`.
