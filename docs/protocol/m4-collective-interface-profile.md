# M4 Collective Interface Runtime Profile

Profile: `CCS-2.1-m4-collective-interfaces-v1`. Compiler: `0.1.0`.
Status: implementation supplement to author-accepted ADR-0004; M4 author exit
and independent final review remain pending. This does not amend CCS-2.1, the
frozen execution plan, M1 semantics, or the eight A-zone schemas.

## Composition and Trust Boundary

`ViewCompiler` requires explicit Registry, authorization and freshness services,
ranker, token counter, native evidence resolver and neutral view renderer.
`compile_view(request, *, compiler=...)` is the functional spelling of the same
operation. No default authority, model counter, current wall-clock time,
network-backed evidence fallback, persistent cache, or activation is supplied.

The evidence resolver must share the exact Registry, authorizer and freshness
objects used by admission. Model ID, tokenizer profile and renderer version
must match the request. Service configuration digests, permission/freshness
snapshots, tokenizer resources/library, lexical-query configuration, and SemVer
comparison profile participate in the B-zone manifest. Missing, malformed or
changing service metadata fails closed.

Inputs are structurally checked before serializers or replay projections.
Task/configuration values are scanned before being retained as safe public
metadata. Nominal PublishedCapsule objects are not proof: actual Registry
revalidation precedes indexing. Failure diagnostics use fixed safe codes and
aggregate rejection counts, not rejected identities, source paths or exception
messages. Replaceable services are trusted executable components, not an OS
sandbox; strict returned data checks and final snapshots defend their interface.

## Admission and Provider Units

Local admission does not require every capsule to provide every task interface.
The complete pre-ranking collection must provide every exact requested `/vN`
interface through one unique usable provider. A provider unit is its full formal
payload plus mandatory closure, not a relevance-selected subset. Every member
must pass individual admission and native exact-source verification.

Root providers are selected from the exact supplied collection, without using
another capsule's lock as a root tie-breaker. Dependencies use the consumer's
exact capsule ID, release version and digest locks. Release SemVer constraints
are separate from `/vN` interface identity. Missing/ambiguous providers, missing
mandatory members, conflicting identities and conflicts block compilation.

M1 remains unchanged. The persistent singleton complete/incomplete/wrong-version/
empty-requirement comparison holds all other gates fixed and compares the M4
complete gate to M1's interface gate. Collective coverage is an explicit runtime
extension, not a reinterpretation of previously reported M1 results.

## Deterministic Assembly

1. Validate request and service binding; revalidate Registry publications and
   locally admit capsule/atom IDs at `request.as_of`.
2. Resolve provider units and graph before ranking. Verify all candidate native
   evidence before supplying canonical admitted atoms to FTS5/BM25.
3. Select every admitted P0 plus closure, render the complete attempt and count
   it. A lexical miss does not remove P0. Overflow returns empty invalid content.
4. Add lexical-hit P1, explicit required atoms and complete root provider units,
   retaining original compression classes. Recompute closure, conflicts and
   exact full-text budget. Any mandatory failure returns empty invalid content.
5. Consider matched P2-P4 atoms in rank order with whole closure groups. An
   optional capacity excess excludes the group; missing dependencies, evidence
   or conflicts still fail closed. Unforced misses remain NOT_RELEVANT.
6. Reauthorize requested exact evidence handles, render complete expansions,
   and repeat full-text counting. No text is appended after budget acceptance.
7. Recheck selected closure, roots, explicit requirements, current admission,
   evidence, request identity and service snapshots before returning the view.

The supported runtime configuration key is `expanded_handles`, a tuple of exact
handle IDs. It is combined with the renderer's configured expansion IDs. Unknown
keys, malformed IDs and unselected/unknown handles block. The neutral renderer
preserves the fixed schema/P0/task/P1-P4 sequence; the compiler checks its exact
sections before counting. P0 statements remain exact, P1 retains full canonical
structure, P2 uses exact excerpts, and P3/P4 use existing source-backed statements.
There is no new summarization, aggregation, model call or provider billing claim.

## Manifest and Replay

`schemas/view-manifest.schema.json` is an independent Draft 2020-12 B-zone schema.
Regenerate it with:

```bash
uv run python -m contractcapsule.compile.schema schemas/view-manifest.schema.json
```

It is not added to the eight-core-schema identity generator. Schema validation
also applies the runtime model's cross-field consistency checks.

The manifest records selected participating capsule references, every admitted
candidate's decision (including excluded candidates), realized dependency/root
provider witnesses, selected closure, expansions, aggregate rejection counts,
full token accounting and validation. Excluded admitted atoms retain provenance
in their decision records even when their capsule is absent from the selected
participating-capsule list. Failed attempts may retain safe attempted counts and
admitted decisions, but never partial content or expansion handles.

Replay identity includes exact input publication projections, task, principal,
budget, evaluation time, model and runtime configuration. B/C data, publication
transport time and expected output digest are excluded. Expected manifest digest
is an output comparison only; mismatch yields `REPLAY_MISMATCH` with empty
content. Replay always recomputes current authorization/freshness and native
source checks. A prior digest cannot authorize revoked evidence.

## Research Limits

These are deterministic implementation fixtures, not human benchmark truth,
formal experiments, or evidence of TER/PIP/BSR or cross-agent effectiveness.
The original M4 schedule ended 2026-08-21; reaching this implementation checkpoint
does not waive the missed G1/G2 dates or the G3 decision. M5 validation, behavioral
contracts, activation, safe-boundary exchange and rollback have not started.
