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

_BoxChars = tuple[str, str, str, str, str, str]  # tl, tr, bl, br, v, h

_BOX_UNICODE: _BoxChars = ("┌", "┐", "└", "┘", "│", "─")
_BOX_ASCII: _BoxChars = ("+", "+", "+", "+", "|", "-")

_STYLE_UNICODE: dict[str, tuple[str, str, str]] = {
    "solid": ("─", "│", "┼"),
    "double": ("═", "║", "╬"),
    "dotted": ("·", ":", "┼"),
    "dashed": ("╴", "╵", "┼"),
    "wave": ("∼", "≀", "┼"),
    "bold": ("━", "┃", "╋"),
    "dot-dash": ("·", "!", "┼"),
    "dot-dot-dash": ("·", "!", "┼"),
}
_STYLE_ASCII: dict[str, tuple[str, str, str]] = {
    "solid": ("-", "|", "+"),
    "double": ("=", '"', "#"),
    "dotted": (".", ":", "+"),
    "dashed": ("-", "'", "+"),
    "wave": ("~", "~", "~"),
    "bold": ("#", "#", "#"),
    "dot-dash": (".", ":", "+"),
    "dot-dot-dash": (".", ":", "+"),
}
_STYLE_DEFAULT = "solid"

# ANSI colour table — the 16 standard terminal colours plus common names.
_ANSI_FG: dict[str, str] = {
    "black": "30", "red": "31", "green": "32", "yellow": "33",
    "blue": "34", "magenta": "35", "cyan": "36", "white": "37",
    "brightred": "91", "brightgreen": "92", "brightyellow": "93",
    "brightblue": "94", "brightmagenta": "95", "brightcyan": "96",
    "grey": "90", "gray": "90", "brightwhite": "97",
}
_ANSI_BG: dict[str, str] = {
    "black": "40", "red": "41", "green": "42", "yellow": "43",
    "blue": "44", "magenta": "45", "cyan": "46", "white": "47",
    "brightred": "101", "brightgreen": "102", "brightyellow": "103",
    "brightblue": "104", "brightmagenta": "105", "brightcyan": "106",
    "grey": "100", "gray": "100", "brightwhite": "107",
}


def _ansi_fg(name: str) -> str:
    return _ANSI_FG.get(name.strip().lower(), "")


def _ansi_bg(name: str) -> str:
    return _ANSI_BG.get(name.strip().lower(), "")


def _apply_color(canvas: list[list[str]], pos: dict, graph: Graph) -> None:
    """Post-process: wrap each node's interior rows in ANSI colour codes."""
    for name, (x0, y0, w, h) in pos.items():
        node = graph.nodes[name]
        fg = _ansi_fg(node.attrs.get("color", ""))
        bg = _ansi_bg(node.attrs.get("fill", ""))
        codes = [c for c in (bg, fg) if c]
        if not codes:
            continue
        start = "\x1b[" + ";".join(codes) + "m"
        end = "\x1b[0m"
        for r in range(1, h - 1):
            row = canvas[y0 + r]
            row[x0] = start + row[x0]
            row[x0 + w - 1] += end


def _box(node: Node, box: _BoxChars) -> list[str]:
    """Render one node as a list of text rows (top border .. bottom border).

    Shape/attribute aware: ``shape: diamond`` draws a rhombus, ``border:
    double/dashed`` changes the frame characters.
    """
    tl, tr, bl, br, v, h = box
    shape = node.attrs.get("shape", "normal")
    border = node.attrs.get("border", "solid")
    if shape == "diamond":
        return _box_diamond(node, border, box)
    pad_x = node.padding_x
    pad_y = node.padding_y
    inner_w = node.inner_width()
    lines = node.label_lines()
    w = node.width()
    hgt = node.height()
    if border == "double":
        h2, v2 = "═", "║"
    elif border == "dashed":
        h2, v2 = "╌", "╎"
    else:
        h2, v2 = h, v
    if shape in ("ellipse", "rounded"):
        tl, tr, bl, br = "╭", "╮", "╰", "╯"
    border_t = tl + h2 * (w - 2) + tr
    rows: list[str] = [border_t]
    for _ in range(pad_y):
        rows.append(v2 + " " * (w - 2) + v2)
    for line in lines:
        right = max(inner_w - len(line), 0)
        rows.append(v2 + " " * pad_x + line + " " * (pad_x + right) + v2)
    for _ in range(pad_y):
        rows.append(v2 + " " * (w - 2) + v2)
    rows.append(bl + h2 * (w - 2) + br)
    return rows


def _box_diamond(node: Node, border: str, box: _BoxChars) -> list[str]:
    """Diamond (rhombus) node — label centered on the widest diagonal row."""
    _, _, _, _, v, h = box
    hch = "═" if border == "double" else h
    vch = "║" if border == "double" else v
    lines = node.label_lines()
    inner_w = node.inner_width()
    half = inner_w // 2
    width = inner_w + 4
    total_rows = len(lines) + 2
    rows: list[str] = []
    for r in range(total_rows):
        if r == 0:
            row = " " * (half + 1) + "/" + hch * max(inner_w - 2, 1) + "\\"
        elif r == total_rows - 1:
            row = " " * (half + 1) + "\\" + hch * max(inner_w - 2, 1) + "/"
        else:
            li = r - 1
            pad = abs(half - li)
            text = lines[li] if li < len(lines) else ""
            left_pad = " " * (pad + 1)
            right_pad = " " * (max(inner_w - len(text), 0) + pad + 1)
            row = left_pad + vch + text + right_pad + vch
        rows.append(row.ljust(width))
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
    styles: dict[str, tuple[str, str, str]],
    *,
    vertical_only: bool = False,
) -> None:
    sx0, sy0, sw, sh = pos[edge.source]
    tx0, ty0, tw, th = pos[edge.target]
    sx = sx0 + sw
    tx = tx0
    sy = sy0 + sh // 2
    ty = ty0 + th // 2
    cx = (sx + tx) // 2 if tx - sx > _CHANNEL else sx + _CHANNEL // 2

    hch, vch, cch = styles.get(edge.style or _STYLE_DEFAULT)

    arrowshape = edge.attrs.get("arrowshape", "")
    if styles is _STYLE_ASCII:
        ar, al = ">", "<"
    elif arrowshape == "filled":
        ar, al = "▶", "◀"
    else:
        ar, al = ">", "<"

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
            left = f"{hch}{hch}" if not edge.directed_from_source else f"{al}{hch}{hch}"
            right = f"{hch}{hch}{ar}" if edge.directed_to_target else f"{hch}{hch}"
            arrow = f"{left} {edge.label} {right}"
        else:
            arrow = f"{hch}{hch}{ar}" if edge.directed_to_target else f"{hch}{hch}"
            if edge.directed_from_source:
                arrow = al + arrow
        start = sx + 1
        end = tx - 1
        width = end - start + 1
        if width > len(arrow):
            cells = [hch] * width
            if arrow.startswith(al):
                cells[0] = al
            if arrow.endswith(ar):
                cells[-1] = ar
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
            put_cross(cx, y, vch)
        return

    def put_corner(x: int, y: int, ch: str) -> None:
        if 0 <= y < len(canvas) and 0 <= x < len(canvas[y]):
            cur = canvas[y][x]
            if cur in (" ", hch, vch):
                canvas[y][x] = ch
            elif cur != ch:
                canvas[y][x] = cch

    # source arm: horizontal sx..cx at row sy, then corner down at cx
    for x in range(sx + 1, cx):
        put(x, sy, hch)
    if sy < ty:
        put_corner(cx, sy, "┌")
    elif sy > ty:
        put_corner(cx, sy, "└")
    # target arm: vertical cx..ty already drawn (vertical_only pass), corner right at cx,ty
    if ty < sy:
        put_corner(cx, ty, "┐")
    elif ty > sy:
        put_corner(cx, ty, "┘")
    for x in range(cx, tx):
        put(x, ty, hch)
    if edge.directed_to_target:
        put(tx - 1, ty, ar)
    if edge.directed_from_source:
        put(sx + 1, sy, al)
    if edge.label:
        mid_y = (lo + hi) // 2
        for i, ch in enumerate(edge.label):
            put(cx + i + 1, mid_y, ch)


def _barycenter_order(layers: list[list[str]], graph: Graph) -> list[list[str]]:
    """Reorder nodes within each layer to reduce edge crossings.

    Sugiyama barycenter heuristic: each node's x position is the average of
    its neighbours' positions in the previous layer; layers are then sorted
    by that average. Iterates top-down then bottom-up until stable.
    """
    order = [list(layer) for layer in layers]
    n_layers = len(order)
    for _ in range(n_layers + 1):
        changed = False
        for direction in (1, -1):
            for li in range(n_layers):
                prev_i = li - direction
                if prev_i < 0 or prev_i >= n_layers:
                    continue
                prev_order = order[prev_i]
                prev_idx = {n: i for i, n in enumerate(prev_order)}
                score: list[tuple[float, int, str]] = []
                for j, n in enumerate(order[li]):
                    neigh = [e.target for e in graph.edges if e.source == n and e.target in prev_idx]
                    neigh += [e.source for e in graph.edges if e.target == n and e.source in prev_idx]
                    if neigh:
                        avg = sum(prev_idx[x] for x in neigh) / len(neigh)
                    else:
                        avg = j
                    score.append((avg, j, n))
                new_order = [x[2] for x in sorted(score)]
                if new_order != order[li]:
                    order[li] = new_order
                    changed = True
        if not changed:
            break
    return order


def render(graph: Graph, *, ascii_style: bool = False, color: bool = False) -> str:
    """Render the graph to multi-line ASCII/Unicode text (no trailing newline)."""
    if not graph.nodes:
        return ""
    box_chars = _BOX_ASCII if ascii_style else _BOX_UNICODE
    styles = _STYLE_ASCII if ascii_style else _STYLE_UNICODE
    bands: list[str] = []
    for comp in _components(graph):
        layers = _barycenter_order(_layers(comp, graph), graph)
        layer_boxes = [[_box(graph.nodes[n], box_chars) for n in layer] for layer in layers]
        col_w = [max(max(len(row) for row in b) for b in boxes) for boxes in layer_boxes]
        col_h = [sum(len(b) for b in boxes) + (len(boxes) - 1) for boxes in layer_boxes]
        y_offs: list[list[int]] = []
        for boxes in layer_boxes:
            offs: list[int] = []
            y = 0
            for b in boxes:
                offs.append(y)
                y += len(b) + 1
            y_offs.append(offs)

        has_groups = any(graph.nodes[n].attrs.get("group") for n in comp)
        pad = 1 if has_groups else 0
        height = (max(col_h) if col_h else 0) + 2 * pad
        width = (sum(col_w) + _CHANNEL * (len(layers) - 1)) + 2 * pad
        canvas = [[" "] * width for _ in range(height)]
        pos: dict[str, tuple[int, int, int, int]] = {}
        x = pad
        for c, boxes in enumerate(layer_boxes):
            for i, b in enumerate(boxes):
                x0 = x
                y0 = y_offs[c][i] + pad
                for r, row in enumerate(b):
                    for cc, ch in enumerate(row):
                        canvas[y0 + r][x0 + cc] = ch
                pos[layers[c][i]] = (x0, y0, len(b[0]), len(b))
            x += col_w[c] + _CHANNEL

        edges_in_comp = [e for e in graph.edges if e.source in pos and e.target in pos]
        for e in edges_in_comp:
            _draw_edge(canvas, pos, e, styles, vertical_only=True)
        for e in edges_in_comp:
            _draw_edge(canvas, pos, e, styles)
        _draw_groups(canvas, pos, graph, box_chars)
        if color:
            _apply_color(canvas, pos, graph)
        bands.append("\n".join("".join(row).rstrip() for row in canvas))
    return "\n\n".join(bands)


def _draw_groups(
    canvas: list[list[str]],
    pos: dict[str, tuple[int, int, int, int]],
    graph: Graph,
    box: _BoxChars,
) -> None:
    """Draw a labelled dashed frame around each group's nodes.

    Groups whose bounding boxes overlap (shared nodes) are merged into a
    single combined frame with a combined label.
    """
    by_group: dict[str, list[str]] = {}
    for n in graph.nodes:
        grp = graph.nodes[n].attrs.get("group")
        if grp and n in pos:
            for g in grp.split(","):
                by_group.setdefault(g, []).append(n)

    def bbox(members: list[str]) -> tuple[int, int, int, int]:
        xs = [pos[m][0] for m in members]
        ys = [pos[m][1] for m in members]
        xe = [pos[m][0] + pos[m][2] for m in members]
        ye = [pos[m][1] + pos[m][3] for m in members]
        x0, x1 = max(min(xs) - 1, 0), min(max(xe) + 1, len(canvas[0]) - 1)
        y0, y1 = max(min(ys) - 1, 0), min(max(ye) + 1, len(canvas) - 1)
        return x0, y0, x1, y1

    def overlap(a: tuple, b: tuple) -> bool:
        return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])

    groups = list(by_group.items())
    merged: list[list[str | set[str]]] = []
    for grp, members in groups:
        bb = bbox(members)
        target: int | None = None
        for idx, (g2, m2) in enumerate(merged):
            if overlap(bb, bbox(list(m2))):
                target = idx
                break
        if target is None:
            merged.append([grp, set(members)])
        else:
            merged[target][0] = f"{merged[target][0]} | {grp}"
            merged[target][1].update(members)

    for grp, members in merged:
        x0, y0, x1, y1 = bbox(list(members))
        for x in range(x0, x1 + 1):
            if canvas[y0][x] == " ":
                canvas[y0][x] = "─"
            if canvas[y1][x] == " ":
                canvas[y1][x] = "─"
        for y in range(y0, y1 + 1):
            if canvas[y][x0] == " ":
                canvas[y][x0] = "│"
            if canvas[y][x1] == " ":
                canvas[y][x1] = "│"
        canvas[y0][x0], canvas[y0][x1] = "┌", "┐"
        canvas[y1][x0], canvas[y1][x1] = "└", "┘"
        label = f" {grp} "
        for i, ch in enumerate(label):
            if x0 + 1 + i <= x1:
                canvas[y0][x0 + 1 + i] = ch
