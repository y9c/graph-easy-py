"""ASCII renderer — draw parsed graphs as terminal box-and-wire diagrams.

Partially faithful port of the *visual* semantics of ``Graph::Easy::As_ascii``
for the supported subset: nodes are boxed; joined components are placed on a
shared horizontal band, separated by edge indicators (``-->``, ``<-``,
``<-->``, or a labeled ``-- label -->``). Independent components stack on
successive bands separated by a blank line.
"""

from __future__ import annotations

from collections import deque

from graph_easy.node import Node
from graph_easy.parser import Edge, Graph


def _box(node: Node) -> list[str]:
    """Render one node as a list of text rows (top border .. bottom border)."""
    pad_x = node.padding_x
    pad_y = node.padding_y
    inner_w = node.inner_width()
    lines = node.label_lines()
    w = node.width()
    h = node.height()
    border = "+" + "-" * (w - 2) + "+"
    rows: list[str] = [border]
    for _ in range(pad_y):
        rows.append("|" + " " * (w - 2) + "|")
    for line in lines:
        right = max(inner_w - len(line), 0)
        rows.append("|" + " " * pad_x + line + " " * (pad_x + right) + "|")
    for _ in range(pad_y):
        rows.append("|" + " " * (w - 2) + "|")
    rows.append(border)
    assert len(rows) == h
    return rows


def _edge_str(edge: Edge) -> str:
    if edge.label:
        return f"-- {edge.label} -->"
    if edge.directed_from_source and edge.directed_to_target:
        return "<-->"
    if edge.directed_from_source:
        return "<--"
    if edge.directed_to_target:
        return "-->"
    return "--"


def _components(graph: Graph) -> list[list[str]]:
    """Split nodes into connected components (preserving insertion order)."""
    adj: dict[str, set[str]] = {n: set() for n in graph.nodes}
    for e in graph.edges:
        if e.source in adj and e.target in adj:
            adj[e.source].add(e.target)
            adj[e.target].add(e.source)
    seen: set[str] = set()
    comps: list[list[str]] = []

    def order(nodes: set[str]) -> None:
        # stable: reuse global insertion order
        pass

    for start in graph.nodes:
        if start in seen:
            continue
        q: deque[str] = deque([start])
        cur: set[str] = set()
        while q:
            u = q.popleft()
            if u in seen:
                continue
            seen.add(u)
            cur.add(u)
            for v in adj[u]:
                if v not in seen:
                    q.append(v)
        comps.append([n for n in graph.nodes if n in cur])
    return comps


def _linearize(comp: list[str], graph: Graph) -> list[str]:
    """Arrange one (traditionally chain-shaped) component left-to-right."""
    indegree = {n: 0 for n in comp}
    outs: dict[str, list[str]] = {}
    for e in graph.edges:
        if e.source in indegree and e.target in indegree:
            outs.setdefault(e.source, []).append(e.target)
            indegree[e.target] += 1
    # Kahn topological order, preferring original insertion order
    ready = [n for n in comp if indegree[n] == 0]
    order: list[str] = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        for m in outs.get(n, []):
            indegree[m] -= 1
            if indegree[m] == 0:
                ready.append(m)
    # attach any remaining (cycles) in insertion order
    for n in comp:
        if n not in order:
            order.append(n)
    return order


def _edge_between(a: str, b: str, graph: Graph) -> Edge | None:
    for e in graph.edges:
        if {e.source, e.target} == {a, b}:
            return e
    return None


def render(graph: Graph) -> str:
    """Render the graph to multi-line ASCII text (no trailing newline)."""
    if not graph.nodes:
        return ""
    bands: list[str] = []
    for comp in _components(graph):
        seq = _linearize(comp, graph)
        boxes = [_box(graph.nodes[n]) for n in seq]
        height = max(len(b) for b in boxes)
        seps = [_edge_between(seq[i], seq[i + 1], graph) for i in range(len(seq) - 1)]
        band: list[str] = []
        for r in range(height):
            cells: list[str] = []
            for i, box in enumerate(boxes):
                cells.append(box[r] if r < len(box) else " " * len(box[0]))
                if i < len(seps):
                    mid = (len(box) - 1) // 2
                    sep = _edge_str(seps[i]) if r == mid and seps[i] is not None else " "
                    cells.append(" " + sep)
            band.append("".join(cells).rstrip())
        bands.append("\n".join(band))
    return "\n\n".join(bands)
