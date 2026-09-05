# M3 Scoped Quality Repair and Independent Exit Reaudit

Date: 2026-09-05. **Technical exit audit: PASS. Human M3 exit: pending.**

The author-authorized scan-scope repair, behavior-preserving refactor,
regressions and new independent audit are complete. No actionable findings
remain in this audit. The earlier failed audit is retained unchanged as
`M3-2026-09-05-independent-audit.md`; this new evidence closes its P2 finding
at the new commit, not by rewriting that earlier verdict.

## Authorization and Exact Commits

Authorized scope: correct scanning, split `_snapshot_source` without changing
behavior, add regressions, and repeat independent audit. No broader semantic,
trust-policy, dependency or next-module work was authorized.

- Baseline: `548af1eabcffccf2ffdfd5c89ab9f1e2dbc9a7d8`.
- Scan fix: `b6f7608c5ba5f6518465e43100724f89b139eba4`.
- Refactor: `2294af30ade13e1aad5507a85976cd80f425c2fc` (audited technical HEAD).
- Existing isolated branch: `codex/m3-post-audit-hotfix-2`.

| Technical file | Change |
|---|---|
| `.gitignore` | only `build/` becomes `/build/`; root build artifacts remain ignored |
| `src/contractcapsule/build/ingest.py` | extract `_read_source_content` and `_validate_source_content`; preserve `_snapshot_source` and public call shapes |
| `tests/unit/test_lint_discovery.py` | three real Ruff discovery regressions |
| `tests/unit/test_source_ingestion_regression.py` | ten before/after ingestion characterizations |

All 26 original test/fixture files are byte-identical to baseline. Registry,
quarantine, core schemas, dependencies, lock, research protocol and both frozen
documents are unchanged. Governance is recorded separately after the technical
audit. No merge, push, branch deletion, M4 or M5 implementation occurred.

## TDD and Behavior Preservation

Before production edits, `uv run pytest tests/unit/test_lint_discovery.py -q -ra`
returned Exit 1 with three failures: two real F821 diagnostic probes were
silently omitted, and inventory comparison found all four Builder files missing.
After only anchoring the ignore rule, the same three tests passed. Fixtures
exercise a real temporary Git repository, project ignore/config rules, an
enclosing repository's broad ignore, and generated root build content. They do
not merely assert an ignore-file string.

The ten ingestion characterizations passed before the refactor and afterward.
They are explicitly not bug RED evidence. Their finalized form also passed
against original baseline production in both implementer and independent-auditor
archives. They cover CAS, exact Git and external sources; bytes and independently
calculated identity metadata; public trust behavior; invalid UTF-8/JSON/YAML and
synthetic secrets; missing/out-of-root/Git-mismatched files; original exceptions;
and absence of CAS or quarantine side effects on those failures.

The independent reviewer additionally compared ASTs: all existing definitions
and signatures are unchanged except the intended function-body extraction;
expanding the two new helper calls reproduces the old `_snapshot_source`
statement sequence exactly. Principal/store selection, locator/Git validation,
secret scan, parser/UTF-8 checks, digest, CAS, metadata, snapshot construction,
second secret scan, proof issuance and registration retain their order.

## Reviews and Independent Execution

- Implementer: internal Codex `m3_lint_scope_implementation`.
- Task reviewer: fresh `m3_lint_scope_task_review`; spec compliance PASS,
  task quality APPROVE, no actionable findings. It inspected the change and
  supporting context but did not rerun the implementer's suite.
- Exit auditor: separate fresh `m3_quality_independent_exit_audit`; independently
  reproduced the gates and fault injections below. Technical M3 exit PASS,
  no actionable findings. This is an AI engineering audit, not human truth.

All requested agents used the explicitly selected internal `gpt-6-astra` tier,
high reasoning. Runtime token and provider-cost metadata were unavailable and
are not inferred from test counts or overall task usage.

The auditor used a fresh exact-HEAD archive, the locked worktree virtual
environment, archive-first `PYTHONPATH`, and external caches. Actual imports
were checked to resolve inside the relevant HEAD/baseline archive. In the table,
`P -m` denotes that locked interpreter, not an unverified system Python.

| Independently run command/check | Exit | Result |
|---|---:|---|
| `P -m pytest tests/unit/test_lint_discovery.py tests/unit/test_source_ingestion_regression.py -q -ra` | 0 | 13 passed |
| `P -m pytest tests/integration/test_build_pipeline.py tests/security/test_trust_promotion.py tests/security/test_trust_gate_remediation.py -q -ra` | 0 | 72 passed |
| `P -m pytest tests/unit/test_models.py tests/unit/test_package_loader.py tests/unit/test_schema_python_parity.py tests/unit/test_cas.py tests/unit/test_registry.py tests/property/test_immutability.py -q -ra` | 0 | 219 passed |
| `P -m pytest tests/fixtures/formal_cases tests/unit/test_spec_lock.py tests/unit/test_ai_usage_ledger.py -q -ra` | 0 | 35 passed |
| `P -m pytest -q -ra`, after mutation restoration | 0 | 339 passed in 9.15s |
| `P -m ruff check .` | 0 | pass |
| `P -m ruff check src/contractcapsule tests --no-respect-gitignore --no-cache` | 0 | pass |
| `P -m ruff check src/contractcapsule tests --select C901,PLR0911,PLR0912,PLR0915` | 0 | pass |
| previous complexity command plus `--no-respect-gitignore --no-cache` | 0 | pass |
| `P -m mypy .` | 0 | 36 files, no issues |
| `uv lock --check --offline` | 0 | 38 packages |
| source worktree and commit-range whitespace checks | 0 | clean |
| exact source/test file inventory versus Ruff | 0 | 36/36, no missing or extra paths; all four Builder files |
| original-node and original-file preservation | 0 | 326 nodes retained, 13 added; 26 original test/fixture files unchanged |
| original-production characterization | 0 | all 10 finalized characterizations passed |
| prior supplemental signature/read/legacy security probes | 0 | 17 passed, separate from committed suite |

Inventory was independently enumerated with `os.walk` and checked against
normal archive scanning, no-ignore archive scanning, and actual Git-worktree
discovery. It contains 18 source and 18 test Python files. Full scanning now
includes Builder and passes the original thresholds, with no new suppressions.

Disjoint committed-suite accounting: `219 + 72 + 35 + 13 = 339`.
The final full run had no skip, xfail or deselection. Main-agent worktree
verification independently passed 339 tests in 8.79s, complete complexity and
36/36 discovery; these repeat checks are not additional study observations.

## Independent Fault Injection

Only disposable archive files were mutated. The source worktree stayed clean.

| Deliberate fault | Persistent regression outcome |
|---|---|
| restore broad `build/` exclusion | Exit 1; 2 diagnostic tests failed, 1 archive-inventory test passed |
| move validation after CAS persistence | Exit 1; 4 validation-failure tests caught actual forbidden persisted blobs |
| remove Registry publication-projection comparison | Exit 1; signature-tamper regression failed with `DID NOT RAISE` |

After restoration, all required gates were rerun and passed, and the complete
79-file technical HEAD archive matched source bytes. Restored SHA-256 values:

```text
.gitignore   f8703dbc7f2e79434cc78caaa336a4af23c89b35a559751642ebd498230e9980
ingest.py    81b2e9e84961e3e8ebaa179a959beabd06e1363f77ba305d89816f437f5b093d
registry.py  2f0afeb76670ece591efa17df6656493c46a730a239371add991f88a8cdde8c9
```

The prior 17 supplemental probes independently confirm signature fields,
read/Blob/replay paths, malformed attestations, fresh-process reads and a
genuine pre-M3 database created by approved M2 commit
`a0dc9c72b210e41699aad6377a21642cac75abf0`. They do not expand the existing
research trust/legacy threat boundary.

## Preserved Failures and Artifacts

Besides intentional RED/mutations, implementation had one new-test nullable
UTC-offset Mypy error and two new-test lint findings (I001 and PLC0414).
Those were corrected without changing production semantics or suppressions,
then all gates reran. An inspection of nonexistent `tests/conftest.py` failed
read-only; the existing integration fixture was reused instead.

The independent audit's initial inventory script raised `ValueError` because
macOS returned `/private/tmp` while the archive was named under `/tmp`.
Resolving both sides corrected that audit-script error. Its traceback remains
in task tool history; it is not relabeled as a product failure or pass.

Raw independent per-command logs and original diagnostic scripts are preserved
in `M3-2026-09-05-quality-audit-evidence.tar.gz` (24 files), SHA-256:
`801174ac95c9f865a341759cc88c1931233f90a21447a7f54f38deaecdd50f99`.
This bundle preserves recorded output bytes; it is not a turnkey anonymous
artifact. Its scripts retain original local paths and require fresh archives
at the recorded revisions. It does not contain the separately recorded tool
traceback. Original temporary evidence remains under
`/tmp/cc-m3-quality-independent.vVWnzT/`; no material data was deleted.

The first native macOS tar packaging attempt inserted 24 AppleDouble metadata
companions that its default listing hid. The main agent's `tarfile` member-count
assertion failed (48 members); its diagnostic then confirmed the companions.
That initial bundle is retained as `evidence-with-appledouble.tar.gz` in the
temporary audit directory. Regeneration with `COPYFILE_DISABLE=1` produced
exactly the 24 intended files. Every final archived file was byte-compared
against its original audit output. No audit output or source byte was changed.

The detailed implementer scratch report remains in this worktree's
`.superpowers/sdd/contractcapsule-m3-lint-scope-remediation-20260905/task-1-report.md`.
Source and test changes are permanently recorded by the two technical commits.

## Frozen and Research Boundaries

Both approved hashes match:

- CCS-2.1: `aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c`.
- Execution plan: `7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0`.

This supplies C2/C5 engineering provenance and RQ2 source-fidelity/trust support
for the System and reproducibility sections. It adds no C1/C3/C4 empirical
result, RQ1 effectiveness/token result, RQ3 TER/PIP/BSR observation, or RQ4
cross-agent/generalization result. No formal experiment or baseline comparison
ran. Codex reviews are not independent human benchmark truth.

The frozen schedule is unchanged: M3 is 20 days past its planned end, G1 is
missed, G2 is due today and G3 tomorrow. No gate is backdated or automatically
approved. No external search or third-party service was used.

**The author must approve the M3 exit gate before M4. 未开始下一模块。**
