# Task 7: Real Compiler Integration and Locked Replay

Date: 2026-09-06. Status: implemented, locally verified and committed; independent
compiler audit and M4 author exit remain pending. No M5, merge, push, external
service, model invocation, experiment, or subagent dispatch was performed.

## Identity, Scope and Inputs

- Worktree: `/Users/litmus/Documents/Contract Capsule/.worktrees/m4-view-compiler`.
- Branch: `codex/m4-view-compiler`.
- Dispatched baseline verified: `73f99aebe519e3b0857c9df5fbbeae99e06ff68c`.
- Task-owned commit: `ccabe4e0ccb2bb49cdb72ef99a8281fec6404486`.
- Controller commits during this task: governance `df760f2`; independent service
  repair `ed7feae`; schema inventory `2ce1653`. These are not this implementer's work.
- Read the task brief, AGENTS instructions, complete frozen spec and execution
  plan (with follow-up ranges for truncated output), accepted ADR-0004, latest
  decision log, actual Task1-6 models/services/fixtures and their task reports.
- Used executing-plans, TDD, incremental implementation, Git workflow and
  verification-before-completion guidance. Existing isolated worktree retained.
- Only 11 owned technical files were staged/committed: compile/{compiler,
  session,validation,manifest,schema}.py; view-manifest.schema.json; integration
  package marker and test_compile_view.py; additive frozen boundary tests in
  test_budget.py and test_eligibility.py; collective runtime protocol supplement.
- Original services, core models, M1 code/fixtures, eight core schema bytes,
  dependencies and lock were not edited by this implementer.
- The controller's `tests/unit/test_models.py` inventory refinement is deliberately
  excluded from this implementer's commit. Full-suite GREEN below includes it;
  it was committed separately as `2ce1653` during report preparation. Reproduce
  the integrated result from that descendant, because the original eight-file-only
  directory assertion rejects the independently required ninth B-zone schema.

Frozen hashes verified at start and after commit:

```text
CCS-2.1 aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c
plan    7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0
```

M4's original end date was 2026-08-21, 16 days before this task date. No schedule
or G1/G2/G3 waiver is inferred. Engineering evidence supports C1/C2/C5 and the
System/compiler section, RQ1's future token accounting and RQ2's selection/source
trace, plus RQ3 prerequisite closure/security gates. It is not C3 benchmark truth,
C4 empirical superiority, TER/PIP/BSR, or RQ4 cross-agent evidence.

## Public Composition and Behavior

`ViewCompiler(registry, authorizer, freshness, ranker, counter, evidence, renderer)`
has no global service defaults. Its primary `compile_view(request)` method returns
the existing CompiledView contract. The functional spelling requires explicit
`compile_view(request, *, compiler=...)` composition. Native evidence must share
the exact Registry, authorizer and freshness objects used by admission.

Raw model trees are checked before serializers can erase malformed fields or
keys. Task/configuration metadata is scanned before its immutable output snapshot
is retained. Request identity uses the existing canonical projection, excluding
B/C, transport publication time and expected output digest. Invalid nominal
requests use sanitized output metadata. Operational exceptions become allowlisted
safe codes and empty invalid content; source paths and exception text are not
returned.

Actual Registry admission precedes graph construction and native source reads;
only admitted canonical atoms whose exact native evidence has been checked reach
the ranker. Returned ranker membership, canonical atom content, uniqueness, score
finiteness and nominal shape are validated. Native material is checked against
the exact owner/record, admitted handle membership, full digest, source span,
resolver version and original evidence-reference set before ranking.

Every admitted P0 and its closure is mandatory, even on lexical miss. The next
mandatory stage adds all matched P1, explicit required IDs and full root provider
payloads without changing their original classes. Optional matched P2-P4 atoms
expand whole closure groups. Budget exclusions drop a whole optional group;
missing dependencies, conflicting groups, evidence errors and mandatory overflow
fail closed. Failed budget attempts retain truthful full-token accounting.

All render attempts use actual selected material and compare the complete neutral
sections before counting the final text. Runtime `expanded_handles` is the only
supported key and combines with the renderer's configured IDs. Explicit handles
must be selected, expand through native reauthorization and fit the full-text
budget. No post-budget text append, summarization, new aggregation, or model call.

Final checks repeat closure, required-unit preservation, request identity, source
material and service snapshots. The final admission recheck occurs after the
last native read and service metadata access, preventing a revocation at that
boundary from returning an earlier-authorized view. These are explicit snapshot
checks, not an OS sandbox or a claim of globally atomic external policy storage.

The manifest contains exact selected participating capsule refs, every admitted
atom's decision, realized root/dependency witnesses and conflicts, selected
closure, expansions, safe denial counts, exact accounting, validation and service
stamps. Excluded admitted atoms retain decision provenance even when their capsule
is absent from selected participation. Service stamps cover compiler/profile,
admission snapshots, FTS5/SQLite/Unicode/query configuration, graph, SemVer library
and comparison semantics, tokenizer library/model/resource hashes, renderer and
evidence configuration. Expected digest comparison never authorizes old content.

The independent B-zone Draft2020-12 schema generator/validator does not modify
the eight-core-schema generator. Its validator also invokes runtime consistency
validation. No false activation permission is present.

## Actual Development Evidence and Corrections

1. Created real Registry integration tests before compiler implementation.
   Initial collection failed because compiler.py did not exist (exit2).
   After the importable public shell, the frozen command exercised actual fixture
   publication and yielded 13 failures/178 passes, with missing implementation
   session/schema paths. These are recorded as missing-implementation failures,
   not as successful behavioral assertions.
2. First complete integration had a NameError in the manifest annotation import.
   Fixed forward annotation; 12 tests passed and one fixture failed publication
   because its capsule ID lacked the required dotted form. Corrected fixture ID;
   no Registry/schema rule was weakened.
3. Broader tests initially had two incorrect setups: a corrupted CAS publication
   was correctly excluded by Registry, leaving an allowed empty candidate rank;
   the fixture now declares the affected atom mandatory to test pre-rank failure.
   The chosen AWS-like secret spelling was not part of M3's documented scanner;
   changed the fixture to its actual supported sk-live pattern.
4. Full pytest exposed an integration package import failure. Added only the
   missing tests/integration/__init__.py marker; no global sys.path hack/config
   change. Full run then had 710 passes and one old schema-directory inventory
   failure. Reported that concrete cross-task conflict to the controller, which
   owns the additive B-zone inventory refinement; all eight equality checks remain.
5. Added a genuine failing test for a dependency witness incorrectly included
   merely because some atom in its consumer capsule was selected. The manifest
   now requires actual selected members and realized source edges. An intervening
   helper-placement edit briefly caused 51 failures; fixed placement, 51 passed.
6. A genuine failing malicious-ranker test showed mutated secret task metadata
   could enter a failure manifest. Captured safe metadata before service calls
   and added request-identity checks. The regression passed without partial output.
7. A conflict regression showed the invalid result omitted its actual admitted
   conflict pair. Added safe realized conflicts to the manifest; test passed.
8. Two genuine failures showed malformed native handle evidence IDs/membership
   could reach ranking on otherwise irrelevant candidates. Added exact record and
   admitted-membership checks before ranking; both now pass.
9. A genuine final-read revocation test returned a valid view after a service
   revoked permissions immediately after its last successful native read. Moved
   final admission checking after all native reads/service snapshots. It now
   returns an invalid empty result. Final focused integration has 55 passing cases.
10. Type/lint corrections were scoped: missing config typing, tuple variadic
    annotation and import/formatting fixes. All four configured complexity rules
    pass without per-function complexity exclusions.

## Persistent Coverage

55 real integration cases plus two added frozen-name boundary cases cover:
nonempty real Registry compilation; P0 misses; P1 and lower-class mandatory
closure; exact and below-budget boundaries; whole optional group exclusions;
mandatory cycles/missing/conflicts; collective providers and singleton M1 parity;
required-provider lower-class overflow; missing/denied/ambiguous providers before
ranking; canonical input permutations; B/C/publication time identity; replay
mismatch and current revocation; malformed ranker/native outputs; configuration
mismatch; Secret/operational faults; stable schema/P0 prefix under malicious
lexical text; native CAS/Git/external source and expansion; actual complete count;
unknown handles; revocation during expansion and after final read; safe decisions
for excluded admitted capsules; and realized-only dependency witnesses.

Existing real Registry graph, lock/version/duplicate-identity tests, native source
faults and resource/token-boundary tests remain in the cumulative suite. No
original test was removed, disabled or narrowed by this implementer. Collection
from an archived author-approved M3 baseline was compared with current collection:
all 339 original node IDs remain; final collection is 745 nodes.

## Disposable Mutation Checks

Copied source/tests into `/private/tmp/ccs-m4-task7-qa.8ZJ1N6` and used separate
fresh interpreter processes with temporary in-memory patches. The preserved
`mutation_check.py` in that directory names each mutation and exact target test.
No product source on disk was mutated. Each case independently returned pytest
exit1, and the probe wrapper returned exit0 only after confirming that expected
failure. The entire set was repeated against the final source snapshot.

- Authorization: bypass atom admission gates; the frozen sentinel observed
  `['allowed', 'denied']` instead of `['allowed']`.
- Closure: replace dependency closure with identity; the integrated view omitted
  the required `dependency` atom.
- Mandatory budget: replace complete accounting with zero counts; P0 overflow
  incorrectly became valid and the frozen test failed.
- Evidence: bypass native full-blob digest and compiler's redundant digest check
  together; a changed external heading with unchanged exact excerpt became valid.
- Replay: spoof the output digest comparison value; the wrong expected digest
  became valid and the replay test failed.

Fresh unmutated reference run of those five exact tests: 5 passed in 1.19s.
These are falsification checks of deterministic fixtures, not formal experiments.

## Verification Commands and Results

All commands ran from the worktree with the local locked Python3.12.13 environment.
The reported final tree includes controller service repair ed7feae and its
coordinated schema-inventory test refinement, subsequently committed as2ce1653.

| Command/check | Actual result |
| --- | --- |
| `uv run pytest -q` | 745 passed, 29.04s, exit0 |
| Frozen four-file M4 pytest command, final `-q` | 235 passed, 16.79s, exit0 |
| Earlier full frozen command with `-v` | 232 passed, 16.52s before last three regression additions |
| `uv run pytest tests/integration/test_compile_view.py -q` | 55 passed, 6.37s |
| `uv run pytest tests/fixtures/formal_cases -v` | 30 passed, 0.08s |
| `uv run mypy .` | success, 70 source files |
| `uv run ruff check .` | pass |
| `uv run ruff check . --no-respect-gitignore --no-cache` | pass |
| C901,PLR0911,PLR0912,PLR0915 normal/no-ignore checks | pass |
| Ruff no-ignore `--show-files` | actual inventory includes all new compiler/tests |
| Original339 node subset check | pass; final745 collected |
| `uv lock --check --offline` | pass,46 packages |
| Independent schema generator to temporary file + `cmp` | byte-identical, exit0 |
| Eight schema/M1 code+fixture diff against approved M3 | empty, exit0 |
| Spec/ledger/schema inventory focused run | 6 passed,0.31s |
| `uv build --offline` | wheel and sdist built successfully |
| Final wheel extraction/import/resource smoke | exact hello-world count2; compiler import; pass |
| `git diff --check` and staged diff check | pass |

Wheel smoke initially used macOS `/tmp`, a symlink to `/private/tmp`; the strict
path policy correctly rejected it as TOKENIZER_UNAVAILABLE. Retesting from the
resolved `/private/tmp` path succeeded. Both expected tokenizer files and license
notice are packaged; profile hash df47711b119989c276e11a040d7a727cb10eff78216c3b1c38614d8aadf63653
and vocabulary hash446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d match.

## Remaining Controller Actions and Limits

- Independently audit this compiler and the final integrated tree; local tests
  and self-found regressions are not independent approval.
- Retain the controller-owned B-zone schema inventory commit2ce1653 and complete
  governance/AI ledger/report updates. This implementer did not stage those files.
- The compiler conservatively fails when any admitted candidate's native source
  is unusable, including an ultimately irrelevant candidate. It does not index
  unverified source material or silently fall back to summaries.
- Exact neutral section comparison is intentionally the M4 neutral renderer
  profile, not a general renderer plug-in system or M6 Agent adapter.
- Source/permission checks use explicit supplied snapshots and configured local
  source mappings. No online origin freshness, external transactional policy
  lock, arbitrary hostile Python sandbox, or activation receipt is claimed.
- AI model identifier, input/output token usage and billed cost are not exposed
  by this subagent execution interface. Do not invent them; controller ledger
  should record actual available metadata and mark unavailable values explicitly.
- Current worktree retains controller-owned changes/reports; this task's 11 files
  are committed. No destructive cleanup was performed, and temporary QA artifacts
  remain available for audit.

M4 exit is pending. **No next module (M5) has started.**
