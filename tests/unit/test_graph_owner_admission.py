"""Explicit graph declarations cannot borrow another admitted source owner."""

from pathlib import Path
from typing import Any

import pytest

from contractcapsule.compile.budget import LocalTokenCounter
from contractcapsule.compile.errors import CompileError
from contractcapsule.models.view import Conflict
from contractcapsule.resolve.graph import resolve_graph
from tests.integration.test_compile_view import pipeline, selection
from tests.unit.test_dependency_closure import (
    ReusedApprovalFixture,
    admit,
    dependencies,
    edge,
    ref,
)
from tests.unit.test_eligibility import task_context


def shared_owner_case(tmp_path: Path, kind: str, denied: bool):
    fixture = ReusedApprovalFixture.create(tmp_path)
    first = fixture.publish(
        atoms=({"atom_id": "a", "scope": ("path:src/only.py",)},)
    )

    def amend(raw: dict[str, Any]) -> None:
        if denied:
            raw["control_manifest"]["scope"]["paths"] = ["src/other/**"]
        target = "absent" if kind == "requires" else "a"
        dependencies((), (), (edge("a", target, kind),))(raw)

    second = fixture.publish(capsule_id="com.example.second", amend=amend)
    task = task_context(paths=("src/only.py", "src/other/file.py"))
    return fixture, (first, second), task


@pytest.mark.parametrize("kind", ["requires", "conflicts"])
def test_denied_source_owner_does_not_contribute_edges(
    tmp_path: Path, kind: str
) -> None:
    fixture, publications, task = shared_owner_case(tmp_path, kind, denied=True)
    admission = admit(fixture, publications, task)
    assert [item.atom_ids for item in admission.items] == [("a",), ()]
    graph = resolve_graph(admission, task)
    assert graph.owners["a"] == (ref(publications[0]),)
    assert graph.close_atoms({"a"}) == {"a"}
    assert graph.conflicts_for({"a"}) == ()


@pytest.mark.parametrize("kind", ["requires", "conflicts"])
def test_admitted_shared_owner_keeps_its_declaration(
    tmp_path: Path, kind: str
) -> None:
    fixture, publications, task = shared_owner_case(tmp_path, kind, denied=False)
    graph = resolve_graph(admit(fixture, publications, task), task)
    assert graph.owners["a"] == tuple(ref(pub) for pub in publications)
    if kind == "requires":
        with pytest.raises(CompileError, match="^MISSING_DEPENDENCY$"):
            graph.close_atoms({"a"})
    else:
        assert graph.conflicts_for({"a"}) == (
            Conflict(source="a", target="a", reason="DECLARED_CONFLICT"),
        )


@pytest.mark.parametrize("kind", ["requires", "conflicts"])
def test_compile_ignores_denied_shared_owner_declarations(
    tmp_path: Path, kind: str
) -> None:
    fixture, publications, task = shared_owner_case(tmp_path, kind, denied=True)
    compiler, request = pipeline(fixture, publications, LocalTokenCounter("owner-test"))
    request = request.model_copy(
        update={"task": task.model_copy(update={"required_atom_ids": ("a",)})}
    )
    view = compiler.compile_view(request)
    assert view.validation.valid, view.validation.blockers
    assert selection(view) == {"a"}
    assert all(
        decision.capsule.capsule_id == "com.example.policy"
        for decision in view.manifest.decisions
    )
