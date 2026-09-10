# M5-1 implementation handoff

Date: 2026-09-10. Implementer recovery subagent. BASE: 104e665.
Candidate commit: bbf031d (source/tests only). Independent review is pending;
this report does not assert an independent PASS or M5 author exit.

Read complete AGENTS.md, CCS-2.1, frozen execution plan, accepted ADR-0005,
derived M5 plan, latest decision-log entries and Task1 brief. Used the required
executing-plans, git-workflow and TDD instructions. Author approval of exact
proposal2842a13 was supplied by the controller and agrees with accepted ADR.
Frozen SHA256s match aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c
and7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0.

The abandoned untracked test was preserved before replacement at
scratch/unfinished-test_execution_contract.py.txt (ignored). It had placeholder
imports, incorrect digest/byte relationships, an unpublished candidate and
one-use verifier expectations. None of that is used as evidence of completion.

## Scope and concrete behavior

Eight added source/test files only. No M1-M4 production file or old test changed.
All nine schemas, dependency declarations/pins and frozen files are byte-identical
to BASE. Main-owned decision-log/ledger changes were not staged or committed.

- Strict frozen ExecutionProfile, Invocation, SubjectProbe, CheckBinding and
  RunnerConfig. Raw extension maps/arrays are adapted without serializing keys
  or values; unknown fields, bool-as-number, null/wrong expectation variants,
  unknown profiles, duplicate check/probe/path IDs and incomplete mappings fail.
- Every clause matches its exact UTF8 SHA256, role, phase and observation
  expectations. Targets distinguish old false/new true; guard, invariant,
  spillover and pair expectations follow accepted ADR.
- Exact old ref, replaces, rollback pointer, old accepted interfaces, new ROOT
  task interfaces, tenant, source repository and risk repeat counts are checked.
- Both publications are read through real Registry.get under principal;
  complete core/signature/status projections must match. B/C projections and
  transport published_at do not define execution identity.
- LocalArtifactResolver uses a frozen explicitly configured digest->package
  map, the existing load_capsule, exact publication projection and actual
  SHA256 rehashing. It snapshots immutable bytes and opens artifact components
  with O_NOFOLLOW and regular-file checks. Later package mutations cannot alter
  already captured bytes. Missing/checksum-mismatched/symlink artifacts fail.
- The complete TestsIntegrity set is rechecked, IDs must be unique, entry points
  must be declared Python files of appropriate kind and every declared helper
  must exist. Executor/probe versus checker subsets are disjoint by ID, folded
  path and verified byte digest, rejecting renamed identical programs.
- Frozen HMAC authority/verifier configuration is request independent; keys
  are repr-hidden. Execution approval binds operation, principal, exact old/new
  core/signature/status, task, source repo/commit, budget/model/tokenizer/renderer,
  profile/image/limits/repeats and the full artifact set including actual bytes.
- UTC issued_at/expiry and domain separation are enforced. Verification is
  reusable; it neither mutates a replay set nor consumes an approval. Unknown,
  absent, forged or malformed approval values return ApprovalError.

## Consumer interfaces

From validate.models:

```python
ReplacementRequest(
    operation_id: str, principal: Principal,
    old: PublishedCapsule, new: PublishedCapsule,
    task: TaskContext, source_repository: str,
    source_commit: str,  # exact sha1:40hex or sha256:64hex
    budget: ViewBudget, model_id: str,
    tokenizer_profile: str, renderer_version: str,
)
BoundExecution(request: ReplacementRequest, profile: ExecutionProfile,
               artifacts: tuple[Artifact, ...])
Artifact(test_id: str, path: str, kind: str, digest: str, data: bytes)
```

Root publications and principal require exact nominal types. Public model
construction never proves publication/approval. parse_execution_contract
revalidates request/task/budget shape before querying authoritative Registry.
Profile fields are the exact ADR names. Tuples preserve ordered checks/probes,
argv and subsets. CheckBinding has optional transport fields old_expected,
new_expected, pair_expected but presence and non-nullness are phase-validated.
Runner CPU accepts exact positive int/float <=1; other positive limits are
strict integers within ADR ceilings. Profile repetitions are1or3 by risk.

```python
# validate.protocols / artifacts
class ArtifactResolver(Protocol):
    def resolve(self, publication: PublishedCapsule) -> tuple[Artifact, ...]: ...
LocalArtifactResolver(packages: Mapping[str, Path])

# validate.contracts
parse_execution_contract(request: ReplacementRequest, registry: Registry,
                         resolver: ArtifactResolver) -> BoundExecution
execution_subject(bound: BoundExecution) -> str  # canonical sha256
# rejection: ExecutionContractError("execution contract rejected")

# validate.approvals
ApprovalAuthority(issuer: str, _key: bytes)  # positional key used by fixtures
authority.issue_execution(bound, *, issued_at: datetime, expires_at: datetime,
                          synthetic: bool) -> Approval
authority.verifier() -> ApprovalVerifier
verifier.verify_execution(approval: object, bound, *, now: datetime) -> Approval
verifier.verify(approval: object, *, domain: Literal["execution", "activation"],
                operation_id: str, subject: str, now: datetime) -> Approval
authority.issue(*, domain, operation_id, subject, issued_at, expires_at,
                synthetic: bool) -> Approval
activation_subject(*, operation_id: str, prepared_digest: str, scope_digest: str,
                   request_digest: str, expected_generation: int) -> str
```

Approval carries issuer/domain/operation_id/subject/issued_at/expires_at/
synthetic/signature. The general activation subject primitive is available for
Task5/6, but actual prepared evidence, generation, scope and revocation remain
owned by the durable transaction controller. Do not accept a caller's arbitrary
subject instead of the controller's recomputation. Approvals are evidence,
not execution consumption receipts. Trusted composition must never export keys
to candidate artifacts/containers.

tests.m5_helpers.M5Fixture.create(root, amend=None, programs=None) supplies real
M3 old/new publications and a complete authored package. It promotes source,
authors an unpublished new capsule and actual program bytes, uses the real
loader receipt/attestation/permit and Registry.publish. No forged proof object.
Programs are SYNTHETIC nonexecuted fixture code; Task4 needs its actual executor
and strict observation checkers. Program labels in this fixture are not human
benchmark ground truth or behavioral execution evidence.

## Actual verification chronology and failures

1. `uv run pytest tests/unit/test_execution_contract.py -q`: exit2, missing
   validate package. This was discovery RED, not behavioral proof.
2. After strict interface skeleton, the real fixture successfully published;
   `uv run pytest tests/unit/test_execution_contract.py::test_real_package_and_repeatable_approval -q`:
   exit1, ExecutionContractError from the unimplemented parse boundary. Actual
   behavior RED; the fixture itself was not failing.
3. Initial implementation:12passed. Expanded negatives:36passed/2failed;
   one test assumed an empty target could publish (already rejected by frozen
   core); the other exposed RegistryNotFound escaping the safe error boundary.
   Corrected honest test ownership and wrapped RegistryError.
4. New malformed nominal-request and lower-CPU-limit tests actually failed
   (DID NOT RAISE and strict int rejection), then implementation corrected
   revalidation and permitted exact fractional lower CPU limits. A duplicate
   test-ID fixture initially omitted bytes because it wrote by renamed ID;
   corrected authoring by path, proving duplicate IDs can reach M5 and are
   rejected there. Reciprocal missing/wrong checksums fail in frozen core.
5. Final focused: `uv run pytest tests/unit/test_execution_contract.py -q`:
   exit0,46passed7.79s.
6. Final accumulated: `uv run pytest -q`: exit0,809passed39.11s
   (763unchanged baseline plus46new). Earlier intermediate run801passed37.56s.
7. `uv run mypy .`: exit0,80files. Ruff normal and --no-respect-gitignore:
   exit0. Four rules C901,PLR0911,PLR0912,PLR0915 both normal/no-ignore: exit0.
   Ruff format changed only new files. Inventory shows80Python +pyproject.
8. `uv sync --locked --offline`: exit0,46resolved/45checked packages.
   `git diff --exit-code 104e665 -- <frozen files> schemas pyproject.toml uv.lock`:
   exit0. `git diff --check` and staged whitespace checks: exit0.
9. Disposable in-process negative mutations (no file changes): replacing
   contracts._disjoint with a no-op makes test_checker_bytes_cannot_alias_executor
   fail with DID NOT RAISE (exit1,1failed0.64s); replacing _check_coverage with a
   no-op makes the exact wrong-clause-SHA256 case fail with DID NOT RAISE
   (exit1,1failed0.64s). Both prove assertions detect removed safety checks.

## Remaining boundaries

Task1 is ready for independent review, not M5 exit. No source execution,
Docker staging, independent view/evidence validation, result attestation,
behavior scoring, runtime tables, action leases, pointer transaction, approval
redemption/revocation or rollback is claimed. These remain Tasks2-6. A closed
artifact subset is an explicit signed allowlist; proving runtime attempted
undeclared imports fail requires Task4's restricted mounts, not static Python
dependency guessing. Current permissions/freshness and full compile dependency
sets are independently checked by Task2 and repeated immediately before run
and commit by later tasks. The byte snapshots here are input to controller-owned
materialization; never run mutable package paths after this boundary.

Evidence supports C1/C2/C5 engineering and prospective RQ3 mechanisms, not C3/C4
or empirical superiority. Frozen original M5 dates are missed; no schedule or
G1-G3 waiver. 未开始下一模块（M6）；本子任务未执行M5-2及以后任务。
