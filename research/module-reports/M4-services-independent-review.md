# Independent Review: M4 Tasks 4-6 at 73f99ae

Date: 2026-09-06. Scope: committed range 4bed753..73f99ae only, reviewed from
the Git archive at /private/tmp/m4-services-review.aUspzT. No production,
governance, existing test, frozen-baseline, or concurrent compiler file was
modified. No subagents were spawned. No M4 exit or author approval is claimed.

## Verdict

Spec compliance: REQUEST CHANGES. Quality/security: REQUEST CHANGES.
Three P1 blockers were reproduced through real publication/Registry/admission
paths. Task 5 has no newly identified blocker in this bounded review; task 4 and
task 6 require fixes and persistent regression tests before acceptance.

## P1: Bind explicit graph declarations to their actual publication owner

Location: src/contractcapsule/resolve/graph.py:358-360; related 292-311 and 267-289.

atomic_edges iterates each publication but passes only the edge to explicit(),
discarding the declaring publication identity. explicit() accepts any globally
known source, and _required_target derives consumers from that named source.
Thus an unrelated admitted capsule can add mandatory dependencies or conflicts
to another capsule even when the declaring capsule is not selected. This is
not a permission-policy implementation issue: all policies in the reproduction
are the honest supplied local services, and the bad relationship is authored
inside a real published graph.

Reproducer: genuine capsule A owns atoms a,b and has no dependency a->b.
Genuine capsule C owns c, has no dependency locks, but its graph declares a->b.
resolve_graph(admit(A,C), task).close_atoms({'a'}) returns {'a','b'} while c is
absent. Both publications pass the real loader, trust permit and Registry.
The edge is effectively attributed to A; C's inclusion/selection and lock
ownership are lost. Conflicts have the same unscoped declaration path.

Required correction: retain declaration owner through assembly, reject foreign
source endpoints unless an explicitly authorized composition semantics exists,
and bind capsule source IDs to the declaring exact publication rather than all
same-name release nodes. Test foreign atom and capsule sources, foreign
conflicts, and same-name publication versions. Preserve genuine local-source
cross-capsule target references and consumer-owned exact locks.

Basis: CCS-2.1 sections 6,9,14,15; ADR-0004 consumer-owned exact requirements,
selected-provider composition, and auditability. This invalidates dependency
provenance and can force otherwise optional context or produce spurious blocks.

## P1: Git expansion can substitute an unapproved span from the same blob

Location: src/contractcapsule/compile/evidence.py:42-43 and 51-64.

The Git branch uses record.locator directly and ignores the approved
extensions['x-source-map']. The Registry verifies the M3 binding against that
x-source-map, not this independent locator. Checking the whole blob digest and
the locator's own span digest therefore proves that the returned bytes exist,
but not that they are the evidence bound to the approved atom.

Reproducer: real trusted Git collection of a two-line Markdown file:
  line 1: # Unrelated heading
  line 2: MUST preserve authorized rule.
Extract line 2, bind it, issue real human-test approval, promote it, and build
the draft. Before its first publication, change only Git locator to line 1,
the SHA-256 of line 1, and symbol_or_heading='invented-anchor'. Keep the original
approved x-source-map and statement. Genuine loader, publication permit,
Registry.publish, and Registry.get all accept it. NativeEvidenceResolver returns
excerpt '# Unrelated heading\n' for approved statement
'MUST preserve authorized rule.'. No approval or signature proof was forged;
no published artifact was edited; no native resolver check was mocked.

The fixture adaptation only omitted unnecessary CAS blobs when loading a Thin
Git capsule, because M4Fixture's CAS-only helper supplies them unconditionally.
The real loader and permit issuance still ran.

Required correction: make the runtime-selected Git locator consistent with the
verified M3 binding, reject locator/x-source-map discrepancies, and check the
declared stable anchor when meaningful. A checksum of another valid span is
not sufficient. Add an end-to-end genuine publication regression, not only a
pure _source_span model_copy test.

Basis: CCS-2.1 sections 8,11.2,14.2 and invariant 8; task-6 source authenticity
and stable-locator requirements. Especially relevant to P2, which renders the
returned excerpt instead of the atom statement.

## P1: Native Git reads may initiate implicit network fetches

Location: src/contractcapsule/compile/evidence.py:125-128, calling existing
build/ingest.py:163-180 and 211-230 without an offline Git execution guard.

--no-replace-objects does not disable partial-clone promisor lazy fetching.
Both cat-file paths may invoke git fetch if a promised object is missing.
Mocking requests.get, as the current tests do, cannot observe this subprocess
transport. A local missing object can therefore cause outbound activity and
potentially source-cache writes rather than a strictly local failure.

Reproducer: create a real local Git source/publication; clone it locally with
--filter=blob:none --no-checkout and uploadpack.allowFilter=true; use that
partial clone as the explicitly configured root and retain the expected origin
identity. Run resolution with GIT_TRACE and diagnostic-only protocol.allow=never
to prevent all actual transport. It safely raises EVIDENCE_UNAVAILABLE only
because the diagnostic forbids transport, and the trace shows:
  git -c fetch.negotiationAlgorithm=noop fetch origin --no-tags
      --no-write-fetch-head --recurse-submodules=no --filter=blob:none --stdin
No external network call was made in this diagnostic; clone setup was file://
between temporary local repositories. Installed Git is 2.50.1 (Apple Git-155).

Required correction: suppress lazy fetch and disallow transports for runtime
Git object resolution, including any Registry source revalidation it invokes.
Test missing promised blob/commit using a real partial clone and transport
sentinel; verify no fetch subprocess and no object-cache mutation. Keep changes
scoped to the actual M4 read path or obtain controller approval for shared
helper changes.

Basis: task-6 explicitly local/no-network/no-fallback/no-writes profile and
CCS-2.1 missing-evidence fail-closed semantics. This is a normal Git repository
configuration, not arbitrary hostile execution inside a trusted policy service.

## Other Reviewed Obligations

- Control Manifest: exact Registry-backed identity and consumer-owned release
  locks are present; graph declaration-owner loss above remains a blocker.
- Semantic Payload: canonical full-content duplicate checks retain owners;
  P0 statements remain contiguous and unchanged with scope/modality/exceptions;
  P1 canonical JSON retains all semantic fields and extensions. No P1 LLM
  rewriting or silent class downgrade was found in these services.
- Evidence Plane: current native reads/expansion reauthorize and bind handles to
  exact capsule/evidence identities; CAS/external full digests, strict UTF-8,
  scanning and safe errors are present. The Git span and offline defects above
  prevent the overall evidence claim. Shared-record sibling/member behavior
  has sparse persistent coverage; no additional bypass was established.
- Dependency Graph: pure cycles terminate; only mandatory requires force
  closure; conflicts are symmetric/deduplicated; whole provider units, partial
  provider rejection, strict release constraints and precise lock witnesses
  are tested. The explicit owner defect compromises assembled semantics.
- Replacement Contract: remains in immutable core; tasks 4-6 neither evaluate
  behavioral contracts nor activate candidates. Those are M5 responsibilities,
  not invented task-4/5/6 acceptance requirements. Final compiler must not
  represent a compiled view as an activation receipt.
- Compression Policy: P0/P1 rendering and exact P2 framing are conservative;
  source P3/P4 statements are reused without generated summaries. Tokenizer
  builds directly from local hash-checked bytes, uses encode_ordinary and strict
  strings, and counts the complete joined text including nonadditive boundaries.
  No network-loading call was found in the counter. Budget selection, mandatory
  P0/P1 closure overflow, provider-unit preservation and expansion rebudgeting
  still require the compiler integration evidence.
- Tests & Integrity: inspected tests and task reports, including reported
  mutation sensitivity. Task-4 reports 85 focused/621 cumulative; task-5 reports
  40 focused/661 cumulative; task-6 reports 18 focused. These are author-reported
  test results, not independent reruns. No full suite was rerun in this review.
  Manifest completeness, replay, final closure/evidence gates and all seven
  modules' collective compiler coverage remain for the final integration audit.

## Verification Record

Read committed AGENTS, both complete frozen baselines, accepted ADR-0004,
latest decision entries, task-4/5/6 briefs/reports, changed source/tests, and
relevant existing models, admission/policies, M3 trust/Registry/source helpers.
Used code-review-and-quality and systematic-debugging guidance. Frozen hashes
verified in the worktree and independently in the committed archive:

- CCS-2.1: aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c
- plan: 7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0
- tokenizer profile: df47711b119989c276e11a040d7a727cb10eff78216c3b1c38614d8aadf63653
- tokenizer vocabulary: 446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d

Independent reproducer: /tmp/m4-services-review-diagnostic.py. Final invocation
uses existing pinned worktree .venv/bin/python with PYTHONDONTWRITEBYTECODE=1
and PYTHONPATH pointing only at the 73f99ae archive source/tests. Exit 0,
three defects reproduced. Final scratch artifacts:
/private/tmp/m4-services-repro-8ohfl1j8 (including git-trace.txt).

Earlier diagnostic setup failures were not product findings: /tmp is a symlink
on macOS, so native fixtures were switched to resolved /private/tmp paths;
CAS-only fixture packaging needed an empty blob map for Thin Git; task paths
were corrected to match the native source atom's actual source.md scope.

No full regression/lint/typecheck result is claimed by this review. M4's frozen
end date 2026-08-21 is 16 days behind the review date; schedule and gates remain
unchanged. Evidence concerns C1/C2/C5 engineering and prospective RQ2/RQ3
prerequisites, not empirical TER/PIP/BSR or benchmark truth. M5 was not started.
