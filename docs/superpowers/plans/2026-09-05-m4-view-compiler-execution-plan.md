# M4 Runtime View Compiler Execution Plan

Status: author requested execution; M3 exit approved; ADR-0004 pending approval.
This is a derived, module-scoped plan, not a replacement for either frozen
baseline. Use `superpowers:executing-plans` and its applicable implementation,
TDD and independent-review workflow after all preceding author gates pass.

## Goal, Baseline and Scope

Compile published capsules into traceable, reproducible runtime views that
respect permissions, mandatory dependencies, evidence and token budgets.
M4 includes Resolver and View Compiler only, not M5 behavioral evaluation,
activation or rollback.

- Author-approved source: `4dbf4849c6e125d1cb5ac8d813e4aeb5dc75694d`.
- Approval-record descendant and M4 branch point:
  `9743b34168e160878b9b9e8132512c540954f511`.
- Isolated branch/worktree: `codex/m4-view-compiler`,
  `.worktrees/m4-view-compiler` at the existing repository root.
- Baseline: 339 committed tests. Preserve all existing tests and frozen inputs.
- Estimated engineering effort: 5-7 days, with audit/author waiting separate.
  The estimate does not change the frozen schedule or lower any gate.

Before execution, fully read AGENTS, CCS-2.1, the frozen execution plan and
latest decisions. Verify these exact SHA-256 values:

```text
CCS-2.1: aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c
Frozen plan: 7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0
```

## Selected Design and Approval Boundary

1. Collective interface coverage follows proposed ADR-0004. Local capsule
   security/scope/freshness/compatibility admission precedes collection coverage,
   which precedes ranking. Preserve M1 unchanged and test singleton equivalence.
   Do not implement this extension before the author accepts the ADR text.
2. `CompileRequest` carries PublishedCapsule values, task, principal, budget,
   explicit `as_of` and renderer configuration. Registry must revalidate the
   exact identity and publication projection; the data class itself is no proof.
3. The author permits two minimal local Python dependencies: `tiktoken` and
   `semantic-version`. Verify and pin package versions and token resources at
   implementation preflight. Runtime must not download assets or guess a model
   mapping; an unavailable matching counter blocks. No vector database or
   external model service is added.
4. `/vN` identifies an exact interface. `capability@constraint` constrains the
   provider capsule's release SemVer. Support `== != > >= < <=` and comma AND;
   expand numeric shorthand to three components. Provider ID, exact release
   string and digest must also agree with the applicable immutable lock.
5. Expected mandatory safety failures produce stable blocker codes, invalid
   validation and empty content. Irrelevant denied candidates may be filtered,
   but missing required interfaces/dependencies block. Rejected objects expose
   only aggregate reason/count diagnostics, not their identifiers.
6. B-zone runtime locks/manifests bind inputs, authorization decisions,
   freshness evidence, counters and service/configuration versions. They do not
   overwrite A-zone locks or justify bypassing current permissions on replay.

ADR-0004 makes two approval-stage details explicit: task-required interfaces
use a provider's whole validated/admissible payload as their required unit;
fine-grained interface-to-atom mapping is not introduced. Root task provider
choice requires one unique usable provider in the exact input collection and
cannot borrow a capsule's dependency lock. Capsule dependencies instead use
their own consumer's exact IntegrityLock entries. These proposed details remain
subject to ADR approval, including their conservative token-budget cost.

## Interfaces and Ordered Tasks

Preserve the five call shapes `eligible`, `rank_atoms`, `dependency_closure`,
`detect_conflicts`, `compile_view`. Stateful capabilities are explicit service
dependencies; graph operations stay pure. No mutable module-default services.

Introduce immutable runtime models: TaskContext, ViewBudget, CompileRequest,
Eligibility, RankedAtom, Conflict, EvidenceHandle, DecisionRecord, ViewManifest,
ValidationReport and CompiledView. CompiledView always contains `content`,
`manifest`, `validation` and `evidence_handles`. Generate a separate B-zone View
Manifest schema; do not change the eight existing core schemas or A-zone identity.

| Task | Deliverable | Required evidence |
|---|---|---|
| M4-1 Contracts and minimal chain | runtime models, service protocols, errors, canonical serialization and one-capsule path | real failing contracts first, stable output shape and immutability |
| M4-2 Admission | Registry verification; lifecycle, tenant, permissions, sensitivity, repository, path, environment, validity, freshness and interface gates | unauthorized atoms never reach ranking; errors/unknown states deny |
| M4-3 Ranking | in-memory FTS5/BM25 over admitted atoms, parameterized SQL and literal query terms | malicious-query and stable-order tests; embedding interface only |
| M4-4 Two-level closure | combine manifest, atom and graph dependencies; lock providers; detect cycles, missing members and conflicts | least fixed point terminates; optional excluded; ambiguity/conflicts block |
| M4-5 Budget and rendering | neutral `ccs-neutral/1.0.0`, P0-P4 ordered assembly | complete rendered-text metering; task/format/handle overhead; no hard-rule truncation |
| M4-6 Evidence and manifest | CAS, trusted local Git and controlled external handles; complete decisions | trace every selected atom; reauthorize/recheck digest and secrets on expansion |
| M4-7 Reproduction and exit | byte-level rebuild, mutations, complete regression, independent audit and records | all gates pass, then stop at M4 author exit |

For each task: behavior-level RED, minimum implementation, GREEN, accumulated
regression, review and focused commit. Checkpoint after M4-2 and M4-4. Shared
interfaces are not concurrently edited by independent implementation agents.

## Algorithm Obligations

- Anchored POSIX segment glob: `*` cannot cross `/`; `**` is a complete segment
  only. Invalid patterns deny, rather than falling back to prefix/substring.
- Every eligible P0 is mandatory. P1 relevance comes from lexical hits, explicit
  task atom references or interface-provision relationships, never LLM guessing.
- Equal atom IDs deduplicate only when canonical content is identical; otherwise
  block. Evidence handles preserve capsule identity to prevent cross-binding.
- Atom dependencies follow explicit references. Mandatory capsule dependencies
  load the provider's whole formal payload, not a metadata-only capsule node.
  A required member denied admission blocks the compilation.
- Add all P0 plus closure, then all related P1 plus closure; either overflow
  requires task splitting or a larger budget. P2-P4 enter in stable whole closure
  groups; reject a group atomically on insufficient room and record why.
- Meter the complete final rendered text with a real tokenizer. Do not assume
  segment counts add; record component counts and boundary adjustment.
- Preserve P0 statement text. P1 permits validated structural normalization
  only; P2 uses exact source excerpts; P3 uses existing source-grounded summaries.
  M4 generates no new summaries. P4 is kept or dropped, without a new aggregator.
- Stable rendering order: schema, P0, task, P1-P4. Source evidence remains data,
  not newly elevated instructions.

## Tests, Evidence and Exit

Required frozen command:

```sh
uv run pytest tests/unit/test_eligibility.py tests/unit/test_dependency_closure.py tests/unit/test_budget.py tests/integration/test_compile_view.py -v
```

Cover cross-tenant/high-ranked unauthorized input, forged PublishedCapsule,
path boundaries, unknown freshness, collective coverage, release constraints,
provider ambiguity, dependency cycles/missing nodes, two-level conflicts and
every budget branch. Include evidence revocation/drift and exact expansion,
input permutations, stable prefixes, complete decision records, unchanged core
digests and locked byte-level reproduction.

Retain the original 339 tests and formal fixtures. Run full Pytest, ordinary
and `--no-respect-gitignore` Ruff/complexity, actual scanned-file membership,
Mypy, lock, frozen hashes, ledger parsing and whitespace checks. Mutations must
prove permission filtering, closure, P0/P1 overflow, evidence integrity and
reproduction regressions catch real failures.

Update the decision log, claim-evidence matrix, AI ledger and M4 module report;
retain failures and independent-audit evidence. Exit requires 100% eligible P0
recall, no unauthorized content in ranking/view, complete mandatory closure and
fail-closed mandatory gates. Report C2/RQ1 metering/RQ2 traces as engineering
evidence only, not formal experiment results. After independent audit, wait for
M4 author approval. **Do not start M5.**

## Current Preparation State

M3 approval has been recorded and the isolated M4 baseline has passed all 339
existing tests. This document and ADR-0004 are preparation artifacts only.
No M4 runtime code, semantic tests, new schema or new dependency is added by
this preparation commit. ADR acceptance remains the next author decision.
