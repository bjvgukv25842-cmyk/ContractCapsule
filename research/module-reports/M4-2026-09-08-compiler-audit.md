# Independent M4 Exit Audit

Verdict: **REQUEST CHANGES**. Date: 2026-09-08, Asia/Shanghai.

Technical candidate: `2ce16535ece97733404e91715bb2b7586b54de20`.
Governance descendant: `cd6cfcf3c7385820862a341db01a6d440509f3bd`.
Approved M3 baseline: `4dbf4849c6e125d1cb5ac8d813e4aeb5dc75694d`.
Reviewer task: `m4_exit_independent_audit`; this reviewer did not author the implementation.

## Findings Requiring Itemized Author Authorization

### IA-M4-01 [P2] Compiler delegates fixed compression-class precedence to the ranker

Location: `src/contractcapsule/compile/session.py:317` (also the unchecked ordering assignment at line 243).

The optional assembly loop consumes `self.ranked` verbatim. The native FTS5 ranker sorts by compression class, but `ViewCompiler` accepts a replaceable `AtomRanker`. Its published protocol declares a list of `RankedAtom`; the compiler verifies shape, complete membership, identity, uniqueness and finite scores, but neither enforces nor rejects out-of-class ordering. Consequently, a different valid relevance order can change the fixed P2-before-P3-before-P4 allocation policy.

Reproduction uses two genuinely Registry-published atoms, one P2 and one P3. Both are real lexical matches. A replacement ranker returns exactly the native FTS5 results in reverse order, without changing any atom, score or matched value. At a 1,400-token budget, the observations are:

| Ranker | Validation | Selected | Excluded |
|---|---|---|---|
| Native FTS5 | valid | `p2` | `p3` |
| Same results, reversed relevance order | valid | `p3` | `p2` |

The reproducer reaches the final selection assertion and fails; it is not an import, fixture-publication or tokenizer-path failure. This is a replaceable-service integration defect, **not a claim that native FTS5 currently sorts incorrectly**. The alternate result satisfies the exposed type/data contract but would violate the native implementation's class-first ordering convention. Because this convention is not an enforced protocol requirement and allocation order is a frozen compiler obligation, the compiler must own or explicitly validate it.

Basis: CCS-2.1 section 11.1 fixes the allocation order; frozen M4 requires P0 -> P1 -> P2 -> P3 -> P4 allocation; the derived plan requires a replaceable ranker boundary and fixed-class whole-closure assembly. Relevance may order atoms within a class, but cannot silently become compression-policy authority.

Minimum repair scope: partition/sort the optional assembly by fixed compression class while preserving rank order inside each class, or reject incompatible ranker ordering with an explicit stable contract. Add a persistent test using a valid non-native ordering and a one-group budget. No schema, core identity, FTS scoring, dependency, or M5 change is necessary. This P2 finding blocks the requested fixed-class sorting acceptance gate until repaired and independently rechecked, or separately resolved by an author-approved interface decision consistent with the frozen plan.

Reproducer: `probes/test_independent_boundaries.py::test_fixed_class_priority_survives_valid_rank_order`.
Evidence: `logs/independent-boundaries.log` and `logs/final-independent-boundaries.log`.

### IA-M4-02 [P2] Late permission denial still exports identities from the old admission snapshot

Locations: `src/contractcapsule/compile/manifest.py:34`, `:43`, `:107`; failure handoff at `src/contractcapsule/compile/session.py:396` and `:401`.

Revoke the authorizer's grants immediately after the final native evidence read, using the same boundary already exercised by the committed late-revocation test. Final reauthorization correctly returns `POLICY_SNAPSHOT_CHANGED` and empty content. However, `failure()` builds its public manifest from the original `session.admission`, `graph`, and selected set. It still includes now-denied identities, the old permission digest, selected decision records, and no updated aggregate denial count.

Observed output after current authorization becomes denied:

```json
{
  "content": "",
  "validation": {"valid": false, "blockers": ["POLICY_SNAPSHOT_CHANGED"]},
  "manifest": {
    "capsules": [{"capsule_id": "com.private.identifier", "version": "1.0.0", "digest": "..."}],
    "decisions": [{"atom_id": "private-identity", "outcome": "selected", "reason": "P0_REQUIRED"}],
    "rejected_counts": {}
  },
  "evidence_handles": []
}
```

The actual full JSON, including exact generated digests, is retained in the log. The diagnostic reaches the identity non-disclosure assertion and fails. The persistent test currently checks the two reads, invalidity and empty content, not the entire public failure projection.

Basis: accepted ADR-0004 section 3 disallows exporting rejected-object identifiers and permits aggregate reasons/counts; current permissions are explicitly rechecked at replay/expansion/output boundaries. The runtime-profile supplement allows retaining **safe admitted** attempted decisions; it does not authorize exporting them after that admission has been invalidated. Historical audit evidence may be retained in an appropriately authorized internal record, but the returned public `CompiledView` is a current output boundary.

Impact is **stale authorized metadata after revocation**, not disclosure of previously never-authorized source text. The caller initially supplied the publication, and the compiler correctly suppresses body text and evidence handles. The defect is that the now-denied public failure projection does not meet the stronger aggregate-only contract the project adopted.

Minimum repair scope: on authorization/snapshot invalidation, produce an aggregate-only safe public failure manifest, or reproject solely from a successfully reauthorized current admission. Do not suppress truthful token attempts for ordinary still-authorized budget failures; do not discard internal audit evidence. Add persistent assertions across capsule refs, atom decisions, providers, conflicts and all identifier-bearing fields after late revocation. This P2 finding blocks the requested current-permission/privacy acceptance gate. No A-zone schema, core data, or M5 change is needed.

Reproducer: `probes/test_independent_boundaries.py::test_late_revocation_does_not_export_now_denied_identity`.
Evidence: `logs/independent-boundaries.log` and `logs/final-independent-boundaries.log`.

## Other Reviewer Finding

The controller communicated the separate scoped review's residual graph declaring-owner admission defect at this candidate: a denied occurrence of a shared atom can still contribute explicit edges through another admitted owner. This reviewer inspected the affected graph assembly but did not duplicate that review's independent repro. It is not counted as a newly discovered finding here, is not considered resolved, and must be incorporated from the scoped review's own evidence. No scoped service PASS or controller-authored rerun was assumed to establish whole-M4 PASS.

## Independent Verification

All commands are recorded with physical cwd, complete argv, exit code and log digest in `commands.jsonl`. Existing dependencies were reused from the locked M4 `.venv`; `PYTHONPATH` directed product and test imports into this reviewer's physical clean archive, verified in `logs/imports.log`. `UV_NO_SYNC=1` and `UV_OFFLINE=1` prevented dependency/environment updates. Pytest cache was disabled and Hypothesis/Ruff/Mypy/uv caches were outside source.

| Check | Result |
|---|---|
| Exact frozen `uv run pytest tests/unit/test_eligibility.py tests/unit/test_dependency_closure.py tests/unit/test_budget.py tests/integration/test_compile_view.py -v` | 235 passed, 16.53s, exit 0 |
| Full Pytest | 745 passed, 29.77s, exit 0 |
| Formal fixtures | 30 passed, exit 0 |
| Ruff ordinary and `--no-respect-gitignore --no-cache` | Both exit 0 |
| C901, PLR0911, PLR0912, PLR0915 ordinary and no-ignore | Both exit 0 |
| Actual Ruff Python-file inventory | 70/70 in archive and worktree, both ignore modes |
| Full Mypy | 70 source files, exit 0 |
| `uv lock --check --offline` | 46 packages, exit 0 |
| Baseline node retention | all original 339 in current 745; 406 additions; missing set empty |
| Independent B-zone schema regeneration | byte-identical to committed ninth schema |
| Eight A-zone schemas | bytes unchanged from M3; all eight regenerate identical structured JSON |
| Governance-focused tests in separate exact descendant archive | 77 passed, exit 0 |
| Offline sdist and wheel build | exit 0 |
| Extracted-wheel compiler/resource smoke | product import points into wheel extraction; local tokenizer counts `hello world` as 2; exit 0 |
| Whitespace baseline-to-governance diff | exit 0 |
| Independent boundary suite | first run 2 failed/8 passed; final 2 failed/9 passed in 5.60s, both failures are findings |
| Independent passing safety subset | 9 passed, 2 finding diagnostics deselected; exit 0 |

The test populations overlap. These are engineering checks, not independent experimental samples, empirical P0 recall on a human benchmark, TER/PIP/BSR results, cross-agent evidence, or author approval.

## Fault Injection

No audited source was modified. Disposable process-local monkeypatches disabled one boundary at a time. The clean independent safety baseline passed first. Each of these eight injections produced one real assertion failure (exit 1), not setup/import errors:

| Injected defect | Detecting independent assertion |
|---|---|
| Skip individual admission gates | denied atom reaches rank input/output |
| Replace closure with identity set | selected dependency missing |
| Zero actual accounting at P0 | overbudget P0 incorrectly returns content |
| Zero actual accounting at P1 | overbudget P1 incorrectly returns content |
| Ignore expected replay manifest | changed task accepted under old expectation |
| Reuse stale external evidence material | changed external bytes accepted at final check |
| Remove root coverage gate | missing provider reaches ranking instead of pre-ranking rejection |
| Disable final required-root preservation | dropped provider sibling accepted |

Two additional mutations independently exercised committed persistent tests: including unadmitted payload members in the coverage inventory fails `test_unusable_root_provider_blocks_before_ranker[denied_member]`; truncating root provider membership to P0/P1 fails `test_required_whole_provider_cannot_drop_lower_class_member`. Logs retain both expected failures. This distinguishes initial coverage enforcement from final preservation and does not treat a setup failure as a killed mutation.

Scripts: `mutate_probe.py`, `run_mutations.py`, `probes/test_independent_boundaries.py`. Logs: `logs/mutation-*.log`.

## Governance And Scope

Fully read AGENTS, both frozen documents, accepted ADR-0004, derived M4 plan, latest decision entries, runtime profile, handoff, and relevant implementation/report evidence. Both frozen hashes match exactly:

- CCS-2.1: `aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c`.
- Frozen plan: `7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0`.

Independent mechanics confirm: all 124 archived tracked Git blobs remain byte-identical; all 94 recorded technical source/test/schema/resource hashes agree with the exact candidate and live worktree; governance adds/changes only 39 `research/` paths; the baseline and technical ledger prefixes are retained, all 40 rows parse, and all six declared exact-UTF8-summary prompt hashes verify; all seven retained gzip failure streams decompress. The one old schema test change is only the authorized ninth-file inventory addition, with the eight equality checks and original node retained. M1 and all formal cases remain unchanged.

Top-level M4 reports and the claim-evidence matrix label controller verification as non-independent, distinguish historical intermediate records, preserve earlier failures, keep M4 exit pending, and do not claim C4/empirical outcomes or author PASS. No new governance blocker was found in this descendant. This does not certify unavailable historical model usage or reproduce historical command times; it checks preserved provenance and independently reruns current claims.

Final recorded state: M4 worktree `cd6cfcf3c7385820862a341db01a6d440509f3bd`, clean; root `c24696e88117b70ed386d586ce9d548951f6287d`, clean. No source, index, branch, governance, dependency, or frozen file was edited by this reviewer. No subagents, third-party plugins, network searches or model CLIs were used.

## Limits And Gate

The standalone diagnostics use the parent temp root as pytest rootdir, while product and helper imports were explicitly verified to use `candidate/`; they are not mistaken for tests installed in the repository. Actual native Registry/M3 fixtures, exact approval-backed publication and the local tokenizer are used. Fixture data and test signing material stay outside the export list.

The first diagnostic run contained ten tests; a further external-source late-drift test was added before final verification. Eight initial safety mutations were followed by two persistent ADR-specific mutations. No setup/import failure required repairing the diagnostic, and no unfavorable result was overwritten. Earlier log files remain intact. The reported provider-429 interruption was an orchestration interruption; the existing checks were resumed without restarting or overwriting their results.

This is not an arbitrary hostile-Python sandbox, online origin-freshness audit, dependency-vulnerability advisory scan, performance benchmark, M5 behavioral activation audit, or proof that every possible failure is covered. Inspection covered the actual models/protocols, admission, FTS5, graph/provider/closure/conflict logic, tokenizer/rendering, native evidence, compiler assembly, failure projection and replay chain, with full automated regression and targeted falsification.

Current date is 18 days after the frozen M4 end date (2026-08-21); the frozen calendar is already in M9 while authorized work remains M4. No deadline pressure waives the outstanding gates.

Stop for item-by-item repair authorization. After separately authorized repairs, rerun affected regressions plus an independent integrated audit before requesting the author's M4 exit approval. **M5 has not started.**

## Minimal Evidence Export

Export only this report; `run_audit.py`, `supplemental.py`, `finalize_evidence.py`, `run_mutations.py`, `mutate_probe.py`, `make_export_manifest.py`, `probes/test_independent_boundaries.py`; `commands.jsonl`, `node-retention.json`, `final-checks.json`; and the `logs/` files. `artifact-manifest.json` locks these small files. Do not export `candidate/`, `baseline/`, `governance/`, `cache/`, `dist/`, `wheel-package/`, pytest fixture directories or any private test keys. All paths above are relative to `/private/tmp/cc-m4-independent-aGz7nzgi`.
