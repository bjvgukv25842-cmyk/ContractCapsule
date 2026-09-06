"""Real Registry, offline tokenizer and native evidence compiler acceptance."""

from dataclasses import replace
from pathlib import Path
from typing import Any, Literal
from unittest.mock import patch

import pytest

from contractcapsule.compile.budget import LocalTokenCounter
from contractcapsule.compile.compiler import ViewCompiler
from contractcapsule.compile.evidence import NativeEvidenceResolver
from contractcapsule.compile.renderers import NeutralViewRenderer
from contractcapsule.models.core import Atom
from contractcapsule.models.view import (
    CompileRequest,
    TaskContext,
    ViewBudget,
    canonical_view_manifest_bytes,
    view_manifest_digest,
)
from contractcapsule.resolve.policies import (
    RecordedFreshnessChecker,
    StaticEligibilityAuthorizer,
)
from contractcapsule.resolve.rank import FTS5BM25Ranker
from contractcapsule.storage.registry import PublishedCapsule
from tests.m4_helpers import M4Fixture
from tests.unit.test_eligibility import (
    AS_OF,
    READER,
    access_grant,
    freshness_for,
    task_context,
)


@pytest.fixture(scope="module")
def counter() -> LocalTokenCounter:
    return LocalTokenCounter("offline-test-model")


def pipeline(
    fixture: M4Fixture, pubs: tuple[PublishedCapsule, ...], counter: LocalTokenCounter
):
    authorizer = StaticEligibilityAuthorizer(grants=(access_grant(),))
    freshness = RecordedFreshnessChecker(
        records=tuple(record for pub in pubs for record in freshness_for(pub).records)
    )
    evidence = NativeEvidenceResolver(fixture.registry, authorizer, freshness, {}, {})
    compiler = ViewCompiler(
        registry=fixture.registry,
        authorizer=authorizer,
        freshness=freshness,
        ranker=FTS5BM25Ranker(),
        counter=counter,
        evidence=evidence,
        renderer=NeutralViewRenderer(),
    )
    request = CompileRequest(
        capsules=pubs,
        task=task_context(text="token"),
        principal=READER,
        budget=ViewBudget(model_input_tokens=10000),
        as_of=AS_OF,
        model_id=counter.model_id,
        tokenizer_profile=counter.profile,
    )
    return compiler, request


def selection(view) -> set[str]:
    return {
        item.atom_id for item in view.manifest.decisions if item.outcome == "selected"
    }


def test_locked_view_is_reproducible(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    fixture = M4Fixture.create(tmp_path)
    pub = fixture.publish(
        atoms=(
            {
                "statement": "token must remain exact.\n",
                "compression_class": "P0_EXACT",
            },
        )
    )
    compiler, request = pipeline(fixture, (pub,), counter)
    with patch("requests.get", side_effect=AssertionError("network forbidden")):
        first = compiler.compile_view(request)
        replay = compiler.compile_view(
            request.model_copy(
                update={
                    "expected_manifest_digest": view_manifest_digest(first.manifest)
                }
            )
        )
    assert first.validation.valid
    assert "token must remain exact." in first.content
    assert first == replay
    assert first.manifest.tokens.total == counter.count(first.content)
    assert selection(first) == {"atom-0"}


def test_p0_miss_and_p1_dependency_are_mandatory(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    def amend(raw: dict[str, Any]) -> None:
        raw["semantic_payload"]["atoms"][1]["requires_atoms"] = ["dependency"]

    fixture = M4Fixture.create(tmp_path)
    pub = fixture.publish(
        atoms=(
            {
                "atom_id": "hard",
                "statement": "Always preserve audit.\n",
                "compression_class": "P0_EXACT",
            },
            {"atom_id": "work", "statement": "token changes here.\n"},
            {
                "atom_id": "dependency",
                "statement": "background prerequisite.\n",
                "compression_class": "P3_SUMMARY",
            },
            {
                "atom_id": "irrelevant",
                "statement": "unrelated history.\n",
                "compression_class": "P3_SUMMARY",
            },
        ),
        amend=amend,
    )
    compiler, request = pipeline(fixture, (pub,), counter)
    view = compiler.compile_view(request)
    assert view.validation.valid
    assert selection(view) == {"hard", "work", "dependency"}
    assert len(view.manifest.decisions) == 4
    assert any(
        link.source == "work" and link.target == "dependency"
        for link in view.manifest.closure
    )


@pytest.mark.parametrize("budget", [0, 1, 100])
def test_mandatory_overflow_is_empty(
    tmp_path: Path, counter: LocalTokenCounter, budget: int
) -> None:
    fixture = M4Fixture.create(tmp_path)
    pub = fixture.publish(atoms=({"compression_class": "P0_EXACT"},))
    compiler, request = pipeline(fixture, (pub,), counter)
    view = compiler.compile_view(
        request.model_copy(update={"budget": ViewBudget(model_input_tokens=budget)})
    )
    assert not view.validation.valid and view.content == ""
    assert "P0_OVERFLOW" in view.validation.blockers
    assert view.manifest.tokens.total > budget


def test_collective_provider_payload_and_permutations(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    fixture = M4Fixture.create(tmp_path)
    pubs = tuple(
        fixture.publish(
            capsule_id="com.example." + name,
            provides=(interface,),
            atoms=(
                {
                    "atom_id": name,
                    "statement": "unmatched provider text.\n",
                    "compression_class": "P3_SUMMARY",
                },
            ),
        )
        for name, interface in (("auth", "auth/v2"), ("audit", "audit/v1"))
    )
    compiler, request = pipeline(fixture, pubs, counter)
    request = request.model_copy(
        update={"task": task_context(required_interfaces=("auth/v2", "audit/v1"))}
    )
    first = compiler.compile_view(request)
    second = compiler.compile_view(
        request.model_copy(update={"capsules": tuple(reversed(pubs))})
    )
    assert first.validation.valid
    assert selection(first) == {"auth", "audit"}
    assert len(first.manifest.providers) == 2
    assert first.content == second.content
    assert canonical_view_manifest_bytes(
        first.manifest
    ) == canonical_view_manifest_bytes(second.manifest)


def test_replay_mismatch_does_not_return_content(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    fixture = M4Fixture.create(tmp_path)
    compiler, request = pipeline(fixture, (fixture.publish(),), counter)
    view = compiler.compile_view(
        request.model_copy(update={"expected_manifest_digest": "sha256:" + "0" * 64})
    )
    assert not view.validation.valid and not view.content
    assert view.validation.blockers == ("REPLAY_MISMATCH",)


@pytest.mark.parametrize(
    "field,value",
    [
        ("model_id", "other"),
        ("tokenizer_profile", "other"),
        ("renderer_version", "other"),
        ("runtime_config", {"unknown": True}),
    ],
)
def test_mismatched_configuration_blocks(
    tmp_path: Path, counter: LocalTokenCounter, field: str, value: object
) -> None:
    fixture = M4Fixture.create(tmp_path)
    compiler, request = pipeline(fixture, (fixture.publish(),), counter)
    view = compiler.compile_view(request.model_copy(update={field: value}))
    assert not view.validation.valid and not view.content


def test_denied_member_never_reaches_ranker(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    fixture = M4Fixture.create(tmp_path)
    pub = fixture.publish(
        atoms=(
            {
                "atom_id": "allowed",
                "statement": "token allowed.\n",
                "compression_class": "P0_EXACT",
            },
            {
                "atom_id": "private-id",
                "statement": "PRIVATE token token token.\n",
                "scope": ("path:other/**",),
            },
        )
    )
    compiler, request = pipeline(fixture, (pub,), counter)
    seen: list[str] = []
    original = FTS5BM25Ranker.rank_atoms

    def sentinel(self: FTS5BM25Ranker, atoms: list[Atom], task: TaskContext):
        seen.extend(atom.atom_id for atom in atoms)
        assert all("PRIVATE" not in atom.statement for atom in atoms)
        return original(self, atoms, task)

    with patch.object(FTS5BM25Ranker, "rank_atoms", sentinel):
        view = compiler.compile_view(request)
    assert view.validation.valid
    assert seen == ["allowed"]
    assert "private-id" not in view.model_dump_json()
    assert "PRIVATE" not in view.model_dump_json()


def test_schema_is_independent_and_reproducible(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    import json

    from contractcapsule.compile.schema import (
        validate_view_manifest,
        view_manifest_schema,
    )

    fixture = M4Fixture.create(tmp_path)
    compiler, request = pipeline(fixture, (fixture.publish(),), counter)
    view = compiler.compile_view(request)
    validate_view_manifest(view.manifest.model_dump(mode="json"))
    root = Path(__file__).parents[2]
    assert (
        json.loads((root / "schemas/view-manifest.schema.json").read_text())
        == view_manifest_schema()
    )


def test_exact_budget_boundary_and_p1_overflow(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    fixture = M4Fixture.create(tmp_path)
    pub = fixture.publish(atoms=({"statement": "token mandatory."},))
    compiler, request = pipeline(fixture, (pub,), counter)
    complete = compiler.compile_view(request)
    total = counter.count(complete.content)
    exact = compiler.compile_view(
        request.model_copy(update={"budget": ViewBudget(model_input_tokens=total)})
    )
    short = compiler.compile_view(
        request.model_copy(update={"budget": ViewBudget(model_input_tokens=total - 1)})
    )
    assert exact.validation.valid and exact.content == complete.content
    assert short.validation.blockers == ("P1_OVERFLOW",) and not short.content
    assert short.manifest.tokens.total == total


def test_optional_group_exclusion_preserves_mandatory_content(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    def amend(raw: dict[str, Any]) -> None:
        raw["semantic_payload"]["atoms"][1]["requires_atoms"] = ["dep"]

    fixture = M4Fixture.create(tmp_path)
    pub = fixture.publish(
        atoms=(
            {
                "atom_id": "hard",
                "statement": "audit always.",
                "compression_class": "P0_EXACT",
            },
            {
                "atom_id": "optional",
                "statement": "token history.",
                "compression_class": "P3_SUMMARY",
            },
            {
                "atom_id": "dep",
                "statement": "background. " * 100,
                "compression_class": "P3_SUMMARY",
            },
        ),
        amend=amend,
    )
    compiler, request = pipeline(fixture, (pub,), counter)
    baseline = compiler.compile_view(
        request.model_copy(update={"task": task_context(text="nomatch")})
    )
    assert baseline.validation.valid and selection(baseline) == {"hard"}
    view = compiler.compile_view(
        request.model_copy(
            update={
                "budget": ViewBudget(
                    model_input_tokens=baseline.manifest.tokens.total + 50
                )
            }
        )
    )
    assert view.validation.valid and selection(view) == {"hard"}
    assert (
        next(
            item.reason
            for item in view.manifest.decisions
            if item.atom_id == "optional"
        )
        == "BUDGET_EXCLUDED"
    )


@pytest.mark.parametrize("fault", ["missing", "conflict", "cycle"])
def test_mandatory_graph_failures_and_cycles(
    tmp_path: Path, counter: LocalTokenCounter, fault: str
) -> None:
    def amend(raw: dict[str, Any]) -> None:
        atoms = raw["semantic_payload"]["atoms"]
        atoms[0]["requires_atoms"] = ["absent" if fault == "missing" else "dep"]
        if fault == "conflict":
            atoms[1]["conflicts_with"] = ["hard"]
        if fault == "cycle":
            atoms[1]["requires_atoms"] = ["hard"]

    fixture = M4Fixture.create(tmp_path)
    pub = fixture.publish(
        atoms=(
            {"atom_id": "hard", "compression_class": "P0_EXACT"},
            {"atom_id": "dep", "compression_class": "P3_SUMMARY"},
        ),
        amend=amend,
    )
    compiler, request = pipeline(fixture, (pub,), counter)
    view = compiler.compile_view(request)
    if fault == "cycle":
        assert view.validation.valid and selection(view) == {"hard", "dep"}
    else:
        assert not view.validation.valid and not view.content
        assert view.validation.blockers == (
            ("MISSING_DEPENDENCY",) if fault == "missing" else ("CONFLICT",)
        )
        if fault == "conflict":
            assert {(item.source, item.target) for item in view.manifest.conflicts} == {
                ("dep", "hard")
            }


@pytest.mark.parametrize("fault", ["drop", "change", "duplicate", "nan", "raise"])
def test_malformed_ranker_results_fail_closed(
    tmp_path: Path, counter: LocalTokenCounter, fault: str
) -> None:
    fixture = M4Fixture.create(tmp_path)
    compiler, request = pipeline(fixture, (fixture.publish(),), counter)
    original = FTS5BM25Ranker.rank_atoms

    def corrupt(self, atoms, task):
        result = original(self, atoms, task)
        if fault == "drop":
            return []
        if fault == "duplicate":
            return result * 2
        if fault == "change":
            return [
                result[0].model_copy(
                    update={
                        "atom": result[0].atom.model_copy(
                            update={"statement": "private leaked"}
                        )
                    }
                )
            ]
        if fault == "nan":
            return [result[0].model_copy(update={"score": float("nan")})]
        raise RuntimeError("private-source-path")

    with patch.object(FTS5BM25Ranker, "rank_atoms", corrupt):
        view = compiler.compile_view(request)
    assert view.validation.blockers == ("RANKING_FAILED",)
    assert not view.content and "private" not in view.model_dump_json()


def test_evidence_integrity_checked_before_ranker(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    fixture = M4Fixture.create(tmp_path)
    pub = fixture.publish(atoms=({"statement": "token important."},))
    compiler, request = pipeline(fixture, (pub,), counter)
    request = request.model_copy(
        update={"task": task_context(required_atom_ids=("atom-0",))}
    )
    record = pub.capsule.evidence_plane.records[0]
    path = fixture.harness.cas.object_path(record.content_digest)
    path.chmod(0o600)
    path.write_bytes(b"tampered")
    with patch.object(
        FTS5BM25Ranker, "rank_atoms", side_effect=AssertionError("must not rank")
    ) as rank:
        view = compiler.compile_view(request)
    assert not view.validation.valid and not view.content
    assert rank.call_count == 0


@pytest.mark.parametrize("mode", ["GIT_IMMUTABLE", "EXTERNAL_IMMUTABLE"])
def test_expansion_is_reauthorized_and_inside_budget(
    tmp_path: Path,
    counter: LocalTokenCounter,
    mode: Literal["GIT_IMMUTABLE", "EXTERNAL_IMMUTABLE"],
) -> None:
    from tests.unit.test_evidence_handles import native_publication

    pub, task, evidence, _ = native_publication(tmp_path, mode)
    compiler = ViewCompiler(
        evidence.registry,
        evidence.authorizer,
        evidence.freshness,
        FTS5BM25Ranker(),
        counter,
        evidence,
        NeutralViewRenderer(),
    )
    request = CompileRequest(
        capsules=(pub,),
        task=task,
        principal=READER,
        budget=ViewBudget(model_input_tokens=10000),
        as_of=AS_OF,
        model_id=counter.model_id,
        tokenizer_profile=counter.profile,
    )
    first = compiler.compile_view(request)
    assert first.validation.valid and first.evidence_handles
    handle = first.evidence_handles[0].handle_id
    expanded = request.model_copy(
        update={"runtime_config": {"expanded_handles": (handle,)}}
    )
    view = compiler.compile_view(expanded)
    assert (
        view.validation.valid
        and "# Evidence\r\nMUST keep native bytes.\r\n" in view.content
    )
    assert view.manifest.expanded_evidence == (handle,)
    assert view.manifest.tokens.total == counter.count(view.content)
    short = compiler.compile_view(
        expanded.model_copy(
            update={
                "budget": ViewBudget(model_input_tokens=first.manifest.tokens.total)
            }
        )
    )
    assert short.validation.blockers == ("EXPANSION_OVERFLOW",) and not short.content
    assert short.manifest.tokens.total == view.manifest.tokens.total


def test_unknown_expansion_blocks(tmp_path: Path, counter: LocalTokenCounter) -> None:
    fixture = M4Fixture.create(tmp_path)
    compiler, request = pipeline(fixture, (fixture.publish(),), counter)
    request = request.model_copy(
        update={"runtime_config": {"expanded_handles": ("sha256:" + "0" * 64,)}}
    )
    view = compiler.compile_view(request)
    assert not view.validation.valid and not view.content


def test_changed_permissions_never_replay_old_view(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    fixture = M4Fixture.create(tmp_path)
    compiler, request = pipeline(
        fixture, (fixture.publish(atoms=({"statement": "token important."},)),), counter
    )
    old = compiler.compile_view(request)
    denied = StaticEligibilityAuthorizer()
    compiler = replace(
        compiler,
        authorizer=denied,
        evidence=replace(compiler.evidence, authorizer=denied),
    )
    replay = compiler.compile_view(
        request.model_copy(
            update={"expected_manifest_digest": view_manifest_digest(old.manifest)}
        )
    )
    assert not replay.validation.valid and not replay.content
    assert not replay.manifest.capsules and not replay.manifest.decisions


def test_secret_task_metadata_is_not_echoed(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    fixture = M4Fixture.create(tmp_path)
    compiler, request = pipeline(fixture, (fixture.publish(),), counter)
    secret = "sk-live-" + "A" * 20
    task = task_context(task_id=secret, text=secret)
    view = compiler.compile_view(request.model_copy(update={"task": task}))
    assert not view.validation.valid and secret not in view.model_dump_json()


def test_policy_snapshot_change_during_ranking_blocks(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    fixture = M4Fixture.create(tmp_path)
    compiler, request = pipeline(fixture, (fixture.publish(),), counter)
    original = FTS5BM25Ranker.rank_atoms

    def revoke(self, atoms, task):
        result = original(self, atoms, task)
        object.__setattr__(compiler.authorizer, "grants", ())
        return result

    with patch.object(FTS5BM25Ranker, "rank_atoms", revoke):
        view = compiler.compile_view(request)
    assert not view.validation.valid and not view.content


def test_service_snapshot_change_during_ranking_blocks(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    fixture = M4Fixture.create(tmp_path)
    compiler, request = pipeline(fixture, (fixture.publish(),), counter)
    original = FTS5BM25Ranker.rank_atoms

    def change(self, atoms, task):
        result = original(self, atoms, task)
        object.__setattr__(self, "version", "2.0.0")
        return result

    with patch.object(FTS5BM25Ranker, "rank_atoms", change):
        view = compiler.compile_view(request)
    assert (
        view.validation.blockers == ("SERVICE_SNAPSHOT_CHANGED",) and not view.content
    )


def test_final_renderer_cannot_drop_p0(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    fixture = M4Fixture.create(tmp_path)
    compiler, request = pipeline(
        fixture, (fixture.publish(atoms=({"compression_class": "P0_EXACT"},)),), counter
    )

    class DroppingRenderer:
        version = "ccs-neutral/1.0.0"
        config_digest = "sha256:" + "1" * 64

        def render(self, task, atoms, evidence):
            return NeutralViewRenderer().render(task, (), ())

    view = replace(compiler, renderer=DroppingRenderer()).compile_view(request)
    assert not view.validation.valid and not view.content


def test_declared_runtime_configuration_is_strict_before_serialization(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    fixture = M4Fixture.create(tmp_path)
    compiler, request = pipeline(fixture, (fixture.publish(),), counter)
    bad_task = request.task.model_copy(update={"unknown": "unsafe"})
    view = compiler.compile_view(request.model_copy(update={"task": bad_task}))
    assert not view.validation.valid and "unsafe" not in view.model_dump_json()


@pytest.mark.parametrize(
    "provides,required,expected",
    [
        (("auth/v2",), ("auth/v2",), True),
        (("auth/v2",), ("auth/v2", "audit/v1"), False),
        (("auth/v1",), ("auth/v2",), False),
        ((), (), True),
    ],
)
def test_singleton_interface_gate_matches_m1(
    tmp_path: Path, counter: LocalTokenCounter, provides, required, expected: bool
) -> None:
    from contractcapsule.formal import BlockerCode, Principal, _eligibility_blockers
    from tests.fixtures.formal_cases.test_formal_cases import (
        CASES_DIR,
        _capsule,
        _load_case,
        _task,
    )

    fixture = M4Fixture.create(tmp_path)
    compiler, request = pipeline(
        fixture, (fixture.publish(provides=provides),), counter
    )
    view = compiler.compile_view(
        request.model_copy(update={"task": task_context(required_interfaces=required)})
    )
    data = _load_case(CASES_DIR / "valid_replacement.json")
    old = _capsule(data["candidate"])
    formal_capsule = replace(
        old, manifest=replace(old.manifest, provides=frozenset(provides))
    )
    formal_task = replace(_task(data["task"]), required_interfaces=frozenset(required))
    m1_allowed = BlockerCode.INCOMPATIBLE_INTERFACE not in _eligibility_blockers(
        formal_capsule, formal_task, Principal(data["principal"])
    )
    assert view.validation.valid == m1_allowed == expected


def test_required_whole_provider_cannot_drop_lower_class_member(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    fixture = M4Fixture.create(tmp_path)
    pub = fixture.publish(
        provides=("auth/v2",),
        atoms=(
            {"atom_id": "small", "statement": "token interface."},
            {
                "atom_id": "large",
                "statement": "background " * 500,
                "compression_class": "P3_SUMMARY",
            },
        ),
    )
    compiler, request = pipeline(fixture, (pub,), counter)
    ordinary = compiler.compile_view(request)
    assert ordinary.validation.valid and selection(ordinary) == {"small"}
    required = request.model_copy(
        update={
            "task": task_context(required_interfaces=("auth/v2",)),
            "budget": ViewBudget(
                model_input_tokens=ordinary.manifest.tokens.total + 50
            ),
        }
    )
    view = compiler.compile_view(required)
    assert view.validation.blockers == ("P1_OVERFLOW",) and not view.content
    assert selection(view) == {"small", "large"}


@pytest.mark.parametrize("case", ["missing", "denied_member", "ambiguous"])
def test_unusable_root_provider_blocks_before_ranker(
    tmp_path: Path, counter: LocalTokenCounter, case: str
) -> None:
    fixture = M4Fixture.create(tmp_path)
    pub = fixture.publish(
        provides=("auth/v2",),
        atoms=(
            {"atom_id": "first"},
            {
                "atom_id": "hidden",
                "scope": ("path:other/**",)
                if case == "denied_member"
                else ("path:src/**",),
            },
        ),
    )
    pubs: tuple[PublishedCapsule, ...] = (pub,)
    if case == "ambiguous":
        pubs += (
            fixture.publish(
                capsule_id="com.example.other",
                provides=("auth/v2",),
                atoms=({"atom_id": "other"},),
            ),
        )
    compiler, request = pipeline(fixture, pubs, counter)
    required = ("auth/v2", "audit/v1") if case == "missing" else ("auth/v2",)
    with patch.object(
        FTS5BM25Ranker, "rank_atoms", side_effect=AssertionError("not reachable")
    ) as rank:
        view = compiler.compile_view(
            request.model_copy(
                update={"task": task_context(required_interfaces=required)}
            )
        )
    assert not view.validation.valid and rank.call_count == 0
    assert not view.content and "hidden" not in view.model_dump_json()


def test_b_c_and_publication_time_do_not_change_replay(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    from contractcapsule.models.canonical import canonical_digest

    fixture = M4Fixture.create(tmp_path)
    pub = fixture.publish(atoms=({"compression_class": "P0_EXACT"},))
    compiler, request = pipeline(fixture, (pub,), counter)
    digest = canonical_digest(pub.capsule)
    first = compiler.compile_view(request)
    changed = replace(
        pub,
        capsule=pub.capsule.model_copy(
            update={
                "derived_artifacts": {"cache": "new"},
                "runtime_sidecar": {"trace": "new"},
            }
        ),
        published_at="2099-01-01T00:00:00Z",
    )
    replay = compiler.compile_view(
        request.model_copy(
            update={
                "capsules": (changed,),
                "expected_manifest_digest": view_manifest_digest(first.manifest),
            }
        )
    )
    assert replay == first
    assert canonical_digest(pub.capsule) == canonical_digest(changed.capsule) == digest


def test_task_change_preserves_schema_and_p0_prefix(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    fixture = M4Fixture.create(tmp_path)
    compiler, request = pipeline(
        fixture,
        (
            fixture.publish(
                atoms=(
                    {
                        "statement": "must preserve audit.",
                        "compression_class": "P0_EXACT",
                    },
                )
            ),
        ),
        counter,
    )
    first = compiler.compile_view(request)
    changed = compiler.compile_view(
        request.model_copy(
            update={
                "task": task_context(text='" OR x* : NEAR(token) DROP TABLE atoms;')
            }
        )
    )
    assert first.validation.valid and changed.validation.valid
    assert (
        first.content.split("BEGIN TASK")[0] == changed.content.split("BEGIN TASK")[0]
    )
    assert "must preserve audit." in changed.content


def test_revocation_at_expansion_blocks_and_hides_raw_error(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    fixture = M4Fixture.create(tmp_path)
    compiler, request = pipeline(
        fixture, (fixture.publish(atoms=({"compression_class": "P0_EXACT"},)),), counter
    )
    view = compiler.compile_view(request)
    handle = view.evidence_handles[0].handle_id
    original = NativeEvidenceResolver.expand

    def revoke(self, handle, principal, task, as_of):
        object.__setattr__(self.authorizer, "grants", ())
        return original(self, handle, principal, task, as_of)

    with patch.object(NativeEvidenceResolver, "expand", revoke):
        changed = compiler.compile_view(
            request.model_copy(
                update={"runtime_config": {"expanded_handles": (handle,)}}
            )
        )
    assert not changed.validation.valid and not changed.content


@pytest.mark.parametrize("boundary", ["scanner", "evidence", "counter"])
def test_operational_faults_return_safe_invalid_view(
    tmp_path: Path, counter: LocalTokenCounter, boundary: str
) -> None:
    fixture = M4Fixture.create(tmp_path)
    compiler, request = pipeline(
        fixture, (fixture.publish(atoms=({"compression_class": "P0_EXACT"},)),), counter
    )
    targets = {
        "scanner": "contractcapsule.compile.validation.scan_secrets",
        "evidence": "contractcapsule.compile.evidence.NativeEvidenceResolver.resolve",
        "counter": "contractcapsule.compile.budget.LocalTokenCounter.count",
    }
    with patch(
        targets[boundary], side_effect=RuntimeError("PRIVATE /private/source/path")
    ):
        view = compiler.compile_view(request)
    assert not view.validation.valid and not view.content
    assert (
        "PRIVATE" not in view.model_dump_json()
        and "/private" not in view.model_dump_json()
    )


def test_injected_evidence_must_share_admission_context(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    fixture = M4Fixture.create(tmp_path)
    compiler, request = pipeline(fixture, (fixture.publish(),), counter)
    compiler = replace(
        compiler,
        evidence=replace(compiler.evidence, authorizer=StaticEligibilityAuthorizer()),
    )
    view = compiler.compile_view(request)
    assert view.validation.blockers == ("INVALID_CONFIGURATION",) and not view.content


def test_changed_external_blob_is_rejected_before_ranking(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    from tests.unit.test_evidence_handles import native_publication

    pub, task, evidence, path = native_publication(tmp_path, "EXTERNAL_IMMUTABLE")
    compiler = ViewCompiler(
        evidence.registry,
        evidence.authorizer,
        evidence.freshness,
        FTS5BM25Ranker(),
        counter,
        evidence,
        NeutralViewRenderer(),
    )
    request = CompileRequest(
        capsules=(pub,),
        task=task,
        principal=READER,
        budget=ViewBudget(model_input_tokens=10000),
        as_of=AS_OF,
        model_id=counter.model_id,
        tokenizer_profile=counter.profile,
    )
    path.write_bytes(b"# Changed\r\nMUST keep native bytes.\r\n")
    view = compiler.compile_view(request)
    assert not view.validation.valid and not view.content
    assert view.validation.blockers == ("EVIDENCE_INTEGRITY",)


def test_admitted_excluded_atom_retains_decision_without_capsule_identity(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    fixture = M4Fixture.create(tmp_path)
    first = fixture.publish(
        capsule_id="com.example.first",
        atoms=({"atom_id": "keep", "compression_class": "P0_EXACT"},),
    )
    second = fixture.publish(
        capsule_id="com.example.second",
        atoms=({"atom_id": "exclude", "statement": "unrelated."},),
    )
    compiler, request = pipeline(fixture, (first, second), counter)
    view = compiler.compile_view(request)
    assert view.validation.valid
    assert [ref.capsule_id for ref in view.manifest.capsules] == ["com.example.first"]
    assert {item.atom_id for item in view.manifest.decisions} == {"keep", "exclude"}


def test_dependency_witness_is_only_reported_when_realized(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    fixture = M4Fixture.create(tmp_path)

    def amend(raw: dict[str, Any]) -> None:
        raw["semantic_payload"]["atoms"][1]["requires_atoms"] = ["target"]
        raw["tests_integrity"]["lock"]["capsule_dependencies"] = [
            {
                "capsule_id": provider.capsule.control_manifest.capsule_id,
                "version": provider.capsule.control_manifest.version,
                "digest": provider.capsule.control_manifest.content_digest,
            }
        ]

    provider = fixture.publish(
        capsule_id="com.example.provider",
        atoms=(
            {
                "atom_id": "target",
                "statement": "unmatched.",
                "compression_class": "P3_SUMMARY",
            },
        ),
    )
    consumer = fixture.publish(
        atoms=(
            {"atom_id": "hard", "compression_class": "P0_EXACT"},
            {
                "atom_id": "optional",
                "statement": "unmatched.",
                "compression_class": "P3_SUMMARY",
            },
        ),
        amend=amend,
    )
    compiler, request = pipeline(fixture, (consumer, provider), counter)
    view = compiler.compile_view(request)
    assert view.validation.valid and selection(view) == {"hard"}
    assert not view.manifest.providers


def test_ranker_cannot_leak_mutated_task_through_failure(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    fixture = M4Fixture.create(tmp_path)
    compiler, request = pipeline(fixture, (fixture.publish(),), counter)
    secret = "sk-live-" + "B" * 20
    original = FTS5BM25Ranker.rank_atoms

    def mutate(self, atoms, task):
        result = original(self, atoms, task)
        object.__setattr__(task, "task_id", secret)
        return result

    with patch.object(FTS5BM25Ranker, "rank_atoms", mutate):
        view = compiler.compile_view(request)
    assert not view.validation.valid and secret not in view.model_dump_json()


@pytest.mark.parametrize("fault", ["evidence_id", "atom_ids"])
def test_malformed_native_material_is_rejected_before_ranking(
    tmp_path: Path, counter: LocalTokenCounter, fault: str
) -> None:
    fixture = M4Fixture.create(tmp_path)
    compiler, request = pipeline(fixture, (fixture.publish(),), counter)
    original = NativeEvidenceResolver.resolve

    def corrupt(self, *args):
        sources = original(self, *args)
        changed = (
            {"evidence_id": "private-evidence"}
            if fault == "evidence_id"
            else {"atom_ids": (*sources[0].handle.atom_ids, "private-atom")}
        )
        return (
            sources[0].model_copy(
                update={"handle": sources[0].handle.model_copy(update=changed)}
            ),
        )

    with (
        patch.object(NativeEvidenceResolver, "resolve", corrupt),
        patch.object(
            FTS5BM25Ranker, "rank_atoms", side_effect=AssertionError("not reachable")
        ) as rank,
    ):
        view = compiler.compile_view(request)
    assert not view.validation.valid and not view.content
    assert rank.call_count == 0
    assert "private-" not in view.model_dump_json()


def test_revocation_after_last_native_read_blocks_output(
    tmp_path: Path, counter: LocalTokenCounter
) -> None:
    fixture = M4Fixture.create(tmp_path)
    compiler, request = pipeline(
        fixture, (fixture.publish(atoms=({"compression_class": "P0_EXACT"},)),), counter
    )
    original = NativeEvidenceResolver.resolve
    calls = 0

    def revoke_after_final_read(self, *args):
        nonlocal calls
        result = original(self, *args)
        calls += 1
        if calls == 2:
            object.__setattr__(self.authorizer, "grants", ())
        return result

    with patch.object(NativeEvidenceResolver, "resolve", revoke_after_final_read):
        view = compiler.compile_view(request)
    assert calls == 2
    assert not view.validation.valid and not view.content
