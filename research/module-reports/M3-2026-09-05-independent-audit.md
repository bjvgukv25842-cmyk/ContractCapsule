# M3 Independent Read-Only Audit, 2026-09-05

## Decision

**Overall technical exit audit: FAIL. Detached-signature repair: PASS.**

One preexisting P2 quality-gate finding remains. This is a completed independent
AI engineering audit, not author approval. M3 remains open; M4 and M5 were not
started. Under phase 0, item 5 of the author's M3/M4 plan, a failed audit stays
in M3 and new remediation requires separate authorization.

## Finding

**P2: Ruff directory discovery silently omits the Builder source package.**

`.gitignore:11` uses unanchored `build/`. In the Git worktree, Ruff applies that
rule to `src/contractcapsule/build/`. Its directory-level success does not prove
all production files were checked. A clean Git archive has no `.git` repository
discovery context, and its full check exposes three violations at
`src/contractcapsule/build/ingest.py:432`, in `_snapshot_source`:

| Rule | Observed | Required maximum |
|---|---:|---:|
| C901 complexity | 17 | 10 |
| PLR0912 branches | 17 | 12 |
| PLR0915 statements | 58 | 50 |

Main-agent reproduction, without changing files:

```sh
git check-ignore -v --no-index src/contractcapsule/build/ingest.py
uv run ruff check src/contractcapsule tests --select C901,PLR0911,PLR0912,PLR0915 --no-cache --verbose
uv run ruff check src/contractcapsule/build/ingest.py --select C901,PLR0911,PLR0912,PLR0915 --no-cache
uv run ruff check src/contractcapsule tests --select C901,PLR0911,PLR0912,PLR0915 --no-respect-gitignore --no-cache
```

The first command identifies `.gitignore:11:build/`. The second returns Exit 0
but explicitly ignores the Builder directory and checks only 30 files. The
third and fourth return Exit 1 with all three violations. Ordinary lint with
`--no-respect-gitignore --no-cache` passes. Both affected files are unchanged
between `79f7f07` and `dc5e87b`; this is not a regression introduced by the
detached-signature repair.

Prior recorded directory-level Ruff successes remain historical command
outputs, but must no longer be interpreted as complete Builder complexity
coverage. No threshold was relaxed and no finding was hidden or repaired in
this audit.

## Targets and Independence

- Previous technical HEAD: `79f7f078d45d6b3b70f56557fdc20bb2f5975f66`.
- Previous governance HEAD: `7d673372aafaef440f0337b578bd93cdfa0d3260`.
- Audited repair HEAD: `dc5e87b79436020f32f858ad62041710cf826947`.
- Branch: `codex/m3-post-audit-hotfix-2`.
- Reviewer: separate internal Codex agent `m3_september_independent_audit`,
  requested model `gpt-6-astra`, high reasoning, fresh context with no session
  transcript. This is not an independent human ground-truth review.
- The reviewer read the complete AGENTS, frozen specification and execution
  plan, M3 report, and relevant decision records. Both frozen hashes matched.
- The exact commit was materialized into a disposable Git archive. Source
  worktree, index and HEAD remained unchanged throughout the review.
- Earlier independent-agent requests failed with HTTP 429 and produced no
  audit findings; they are not counted as completed reviews. The successful
  review is the explicitly identified agent above.

## Repair and Security Findings

No new security, correctness or compatibility defect was found in this repair.
After verifying the stored permit's trust-root signature, Registry compares
the reconstructed Capsule's signature-inclusive publication projection with
the authenticated `loader_attestation.publication_digest`.

- `get`, publication replay, `can_read_blob` and `get_blob` pass through stored
  publication verification. Changed signature values/envelopes are rejected;
  incompatible algorithm/key identifiers fail earlier during reconstruction.
- Missing attestations, malformed JSON or non-object payloads, missing loader
  data, wrong-type digests and empty digests fail closed.
- New P0/P1 publication still requires the existing mandatory M3 trust gate.
  Candidate, Evidence, version, approval and source bindings are not weakened.
- Fresh-process reads validate using the same TrustRoot and do not depend on
  the prior process's ephemeral loader HMAC.
- A real approved M2 `a0dc9c7` archive created a pre-M3 P0 database. Current
  Registry read, Blob access and exact no-write replay succeeded after upgrade.
  This preserves the existing migration boundary, not a guarantee against an
  adversary replacing all database content and its legacy history.
- The frozen canonical A-zone identity and eight core schemas are unchanged.

## Independent Verification

The reviewer used the target worktree's locked virtual environment and loaded
the archive via `PYTHONPATH`, with bytecode disabled and caches outside source.
The following command suffixes were executed with that environment's tools:

| Command/check | Exit | Result |
|---|---:|---|
| `pytest tests/integration/test_build_pipeline.py tests/security/test_trust_promotion.py tests/security/test_trust_gate_remediation.py -q -ra` | 0 | 72 passed |
| `pytest tests/unit/test_models.py tests/unit/test_package_loader.py tests/unit/test_schema_python_parity.py tests/unit/test_cas.py tests/unit/test_registry.py tests/property/test_immutability.py -q -ra` | 0 | 219 passed |
| `pytest tests/fixtures/formal_cases tests/unit/test_spec_lock.py tests/unit/test_ai_usage_ledger.py -q -ra` | 0 | 35 passed |
| `pytest -q -ra`, after restoring mutation | 0 | 326 passed in 7.58s |
| default Ruff | 0 | pass in archive |
| Mypy | 0 | no issues in 34 source files |
| extended Ruff complexity | 1 | three violations above |
| `uv lock --check --offline` | 0 | 38 packages |
| frozen hashes, protected-file diff, whitespace | 0 | unchanged/clean |
| independent disposable probes | 0 | 17 passed |

The main agent also reran the complete committed suite: 326 passed in 7.86s,
and independently reran all 17 reviewer probes: 17 passed in 1.30s. Probe runs
are supplementary diagnostics, not additions to the 326 committed tests.

Disjoint committed-test accounting: `219 + 72 + 30 + 4 + 1 = 326`.

## Mutation and Preserved Failures

The reviewer removed only the call to
`_verify_attested_publication_projection(payload, capsule)` in the disposable
archive. The committed regression
`test_m3_attestation_rejects_persisted_detached_signature_tamper` returned
Exit 1 with `DID NOT RAISE PublicationIntegrityError`. Restoring the call made
the node pass and the full 326-test suite pass again.

Restored Registry source SHA-256, independently matched to the source worktree:
`2f0afeb76670ece591efa17df6656493c46a730a239371add991f88a8cdde8c9`.

Failed attempts retained rather than relabeled as successful checks:

- Before this audit, the implementer observed real regression RED, then GREEN,
  then comparison-removal mutation RED and restored GREEN. An initial M2
  command referenced nonexistent test files and exited 4 without running tests.
- The reviewer first selected the root worktree's older virtual environment;
  missing `rfc8785` caused three collection errors. Selecting the target locked
  environment and archive import paths resolved this setup error.
- Two initial probe assertions demanded overly narrow error messages while
  the code already rejected incompatible signatures at reconstruction. Their
  assertions were corrected to allow that earlier safe rejection; all 17
  probes then passed. No production code changed to satisfy them.
- Full complexity checking fails as documented above. This failure remains
  open, regardless of the passing behavioral suites.

## Reproduction Artifacts

The exact independent probe source is preserved byte-for-byte beside this
report as `M3-2026-09-05-audit-probes.py.txt`, SHA-256:
`90ad59aba19edcd1c1c9bc061c874cb86b5997cf4b15307bcddc2be594d5d4ed`.
Its `.txt` suffix keeps one-off audit probes outside routine test discovery.
It contains the original temporary paths, which must be recreated or explicitly
mapped when replaying outside the original machine. They are not paper-ready
anonymous artifact paths.

Original temporary artifacts remain available at:

- exact-HEAD archive: `/tmp/cc-m3-independent-audit.fGxtb6`;
- M2 archive: `/tmp/cc-m2-legacy-origin.JPjfzG`;
- original probes and cache/temp directories: `/tmp/cc-m3-audit-cache.iVQA11`;
- main-agent supplemental rerun: `/tmp/contractcapsule-m3-governance-20260905.iCvDUZ`.

Raw command outputs are in the task's tool records; there is no separately
captured raw-log file. The report does not claim otherwise. Archive Git objects
are reproducible from the exact commit IDs recorded above.

## Author Decision and Research Boundary

Requested next authorization is limited to correcting Builder lint discovery,
splitting `_snapshot_source` without behavioral changes, adding a discovery
regression check, rerunning all original gates without weakening thresholds,
and conducting another independent audit. This recommendation is not executed.
After a clean audit, the author must still approve the M3 exit gate before M4.

The original G1 deadline has passed; G2 is due on 2026-09-05 with prerequisites
absent; G3 is 2026-09-06. No gate is backdated or declared passed, and the frozen
schedule remains unchanged. Structural schedule decisions require an ADR.

C2/C5 engineering provenance and RQ2's integrity substrate are supported by
these tests. No benchmark, formal experiment, TER/PIP/BSR measurement, baseline
comparison, or C2-C5 empirical result was generated. Frozen hashes are:

- CCS-2.1: `aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c`;
- execution plan: `7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0`.

No Skywork Search or other external search/plugin service was called. No merge,
push, M4 implementation or M5 implementation occurred. **M3 exit remains open.**
