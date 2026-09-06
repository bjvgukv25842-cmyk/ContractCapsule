"""Pure symmetric conflict detection."""

from contractcapsule.models.core import DependencyGraph
from contractcapsule.models.view import Conflict


def detect_conflicts(selected: set[str], graph: DependencyGraph) -> list[Conflict]:
    pairs = {
        tuple(sorted((edge.source, edge.target)))
        for edge in graph.edges
        if edge.edge_type == "conflicts"
        and edge.source in selected
        and edge.target in selected
    }
    return [
        Conflict(source=source, target=target, reason="DECLARED_CONFLICT")
        for source, target in sorted(pairs)
    ]
