"""ASCII renderer — draw parsed graphs as terminal box-and-wire diagrams.

Port of the visual semantics of ``Graph::Easy::As_ascii`` for the supported
subset, laid out on a character canvas:

* nodes are boxed and grouped into horizontal layers (longest-path layering)
* within a layer, nodes stack vertically
* edges connect layers with arrows; the connector style selects the line
  characters (``--`` solid, ``..`` dotted, ``==`` double, ``~~`` wave,
  ``##`` bold); vertical runs and arrowheads follow the same style.

Independent components render as separate stacked diagrams.
"""

from __future__ import annotations

from collections import deque

from graph_easy.node import Node
from graph_easy.parser import Edge, Graph

_CHANNEL = 9

_STYLE_CHARS: dict[str, tuple[str, str, str]] = {
    "solid": ("-", "|", "+"),
    "dotted": (".", ":", "+"),
    "double": ("=", '"', "#"),
    "dashed": ("-", "'", "+"),
    "wave": ("~", "~", "~"),
    "bold": ("#", "#", "#"),
    "dot-dash": (".", ":", "+"),
    "dot-dot-dash": (".", ":", "+"),
}
_STYLE_DEFAULT = "solid"


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


def _components(graph: Graph) -> list[list[str]]:
    """Split nodes into connected components (preserving insertion order)."""
    adj: dict[str, set[str]] = {n: set() for n in graph.nodes}
    for e in graph.edges:
        if e.source in adj and e.target in adj:
            adj[e.source].add(e.target)
            adj[e.target].add(e.source)
    seen: set[str] = set()
    comps: list[list[str]] = []
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


def _layers(comp: list[str], graph: Graph) -> list[list[str]]:
    """Longest-path layering: rank[v] = 1 + max(rank[u]) over edges u->v."""
    rank = {n: 0 for n in comp}
    for _ in range(len(comp)):  # longest path needs at most len-1 passes
        changed = False
        for e in graph.edges:
            if e.source in rank and e.target in rank and rank[e.target] <= rank[e.source]:
                rank[e.target] = rank[e.source] + 1
                changed = True
        if not changed:
            break
    by_rank: dict[int, list[str]] = {}
    for n in comp:
        by_rank.setdefault(rank[n], []).append(n)
    return [by_rank[r] for r in sorted(by_rank)]


def _draw_edge(
    canvas: list[list[str]],
    pos: dict[str, tuple[int, int, int, int]],
    edge: Edge,
    *,
    vertical_only: bool = False,
) -> None:
    sx0, sy0, sw, sh = pos[edge.source]
    tx0, ty0, tw, th = pos[edge.target]
    sx = sx0 + sw
    tx = tx0
    sy = sy0 + sh // 2
    ty = ty0 + th // 2
    cx = sx + _CHANNEL // 2

    hch, vch, cch = _STYLE_CHARS.get(edge.style or _STYLE_DEFAULT)

    def put(x: int, y: int, ch: str) -> None:
        if 0 <= y < len(canvas) and 0 <= x < len(canvas[y]):
            canvas[y][x] = ch

    def put_cross(x: int, y: int, ch: str) -> None:
        if 0 <= y < len(canvas) and 0 <= x < len(canvas[y]):
            if canvas[y][x] == " ":
                canvas[y][x] = ch
            elif canvas[y][x] != ch:
                canvas[y][x] = cch

    if sy == ty:
        if vertical_only:
            return
        if edge.label:
            left = f"{hch}{hch}" if not edge.directed_from_source else f"<{hch}{hch}"
            right = f"{hch}{hch}>" if edge.directed_to_target else f"{hch}{hch}"
            arrow = f"{left} {edge.label} {right}"
        else:
            arrow = f"{hch}{hch}>" if edge.directed_to_target else f"{hch}{hch}"
            if edge.directed_from_source:
                arrow = "<" + arrow
        start = sx + 1
        end = tx - 1
        width = end - start + 1
        if width > len(arrow):
            cells = [hch] * width
            if arrow.startswith("<"):
                cells[0] = "<"
            if arrow.endswith(">"):
                cells[-1] = ">"
            for i, ch in enumerate(cells):
                put(start + i, sy, ch)
        else:
            for i, ch in enumerate(arrow):
                put(start + i, sy, ch)
        return

    # route the vertical arm from the source's bottom edge so it never
    # collides with horizontal arrows leaving the source's mid row
    sy = sy0 + sh - 1
    lo, hi = (sy, ty) if sy < ty else (ty, sy)
    if vertical_only:
        for y in range(lo + 1, hi):
            put_cross(cx, y, "|")
        return

    for x in range(sx + 1, cx):
        put(x, sy, hch)
    for x in range(cx, tx):
        put(x, ty, hch)
    if edge.directed_to_target:
        put(tx - 1, ty, ">")
    if edge.directed_from_source:
        put(sx + 1, sy, "<")
    if edge.label:
        mid_y = (lo + hi) // 2
        for i, ch in enumerate(edge.label):
            put(cx + i + 1, mid_y, ch)


def render(graph: Graph) -> str:
    """Render the graph to multi-line ASCII text (no trailing newline)."""
    if not graph.nodes:
        return ""
    bands: list[str] = []
    for comp in _components(graph):
        layers = _layers(comp, graph)
        layer_boxes = [[_box(graph.nodes[n]) for n in layer] for layer in layers]
        col_w = [max(len(b[0]) for b in boxes) for boxes in layer_boxes]
        col_h = [sum(len(b) for b in boxes) + (len(boxes) - 1) for boxes in layer_boxes]
        y_offs: list[list[int]] = []
        for boxes in layer_boxes:
            offs: list[int] = []
            y = 0
            for b in boxes:
                offs.append(y)
                y += len(b) + 1
            y_offs.append(offs)

        height = max(col_h) if col_h else 0
        width = sum(col_w) + _CHANNEL * (len(layers) - 1)
        canvas = [[" "] * width for _ in range(height)]
        pos: dict[str, tuple[int, int, int, int]] = {}
        x = 0
        for c, boxes in enumerate(layer_boxes):
            for i, b in enumerate(boxes):
                x0 = x
                y0 = y_offs[c][i]
                for r, row in enumerate(b):
                    for cc, ch in enumerate(row):
                        canvas[y0 + r][x0 + cc] = ch
                pos[layers[c][i]] = (x0, y0, len(b[0]), len(b))
            x += col_w[c] + _CHANNEL

        edges_in_comp = [e for e in graph.edges if e.source in pos and e.target in pos]
        for e in edges_in_comp:
            _draw_edge(canvas, pos, e, vertical_only=True)
        for e in edges_in_comp:
            _draw_edge(canvas, pos, e)
        bands.append("\n".join("".join(row).rstrip() for row in canvas))
    return "\n\n".join(bands)
