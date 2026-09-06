"""Pure mandatory dependency closure."""

from contractcapsule.models.core import DependencyGraph


def dependency_closure(selected: set[str], graph: DependencyGraph) -> set[str]:
    dependencies: dict[str, set[str]] = {}
    for edge in graph.edges:
        if edge.edge_type == "requires" and edge.mandatory:
            dependencies.setdefault(edge.source, set()).add(edge.target)
    closed = set(selected)
    pending = list(selected)
    while pending:
        for target in dependencies.get(pending.pop(), set()):
            if target not in closed:
                closed.add(target)
                pending.append(target)
    return closed
