"""ASCII renderer — draw parsed graphs as terminal box-and-wire diagrams.

Port of the visual semantics of ``Graph::Easy::As_ascii`` for the supported
subset, laid out on a character canvas:

* nodes are boxed and grouped into horizontal layers (longest-path layering)
* within a layer, nodes stack vertically
* edges connect layers with arrows; the connector style selects the line
  characters (``--`` solid, ``..`` dotted, ``==`` double, ``~~`` wave,
  ``##`` bold); vertical runs and arrowheads follow the same style
* edges that skip layers and back edges (cycles) are routed through detour
  rows below the diagram so they never overwrite other boxes
* self loops are drawn as a small loop leaving the node's right side

Line segments merge at shared cells into proper junction glyphs (``┬``,
``┴``, ``┼``, ...) instead of overwriting each other. Independent
components render as separate stacked diagrams.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from graph_easy.node import Node
from graph_easy.parser import Edge, Graph

_CHANNEL = 5
_STYLE_DEFAULT = "solid"

# Direction bits used to merge line segments into junction glyphs.
L, R, U, D = 1, 2, 4, 8

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

# Junction glyph for each connection mask (two or more directions).
# Straight masks (L|R, U|D) are intentionally absent: their glyph depends on
# the line style, so they fall back to the style's own char via merge().
_JOIN_UNICODE = {
    L | D: "┐",
    R | D: "┌",
    L | U: "┘",
    R | U: "└",
    L | R | U: "┬",
    L | R | D: "┴",
    U | D | L: "┤",
    U | D | R: "├",
    U | D | L | R: "┼",
}
_JOIN_ASCII = {
    L | D: "+",
    R | D: "+",
    L | U: "+",
    R | U: "+",
    L | R | U: "+",
    L | R | D: "+",
    U | D | L: "+",
    U | D | R: "+",
    U | D | L | R: "+",
}

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


@dataclass
class _CharSet:
    """One output charset: box chars, line styles, arrows, join tables."""

    box: _BoxChars
    styles: dict[str, tuple[str, str, str]]
    ar: str  # arrowhead on the target end of a forward edge ('-->')
    al: str  # arrowhead pointing left (source end '<--', back edge end)
    ar_up: str  # arrowhead pointing up (self-loop re-entry)
    join: dict[int, str]
    mask_of: dict[str, int]

    @classmethod
    def make(cls, ascii_style: bool) -> _CharSet:
        join = _JOIN_ASCII if ascii_style else _JOIN_UNICODE
        styles = _STYLE_ASCII if ascii_style else _STYLE_UNICODE
        mask_of: dict[str, int] = {}
        for m, g in join.items():
            mask_of.setdefault(g, m)
        for hch, vch, _cch in styles.values():
            mask_of.setdefault(hch, L | R)
            mask_of.setdefault(vch, U | D)
        if ascii_style:
            # A box corner '+' and a line junction '+' look identical.
            mask_of["+"] = L | R | U | D
        return cls(
            box=_BOX_ASCII if ascii_style else _BOX_UNICODE,
            styles=styles,
            ar=">" if ascii_style else "▶",
            al="<" if ascii_style else "◀",
            ar_up="^" if ascii_style else "▲",
            join=join,
            mask_of=mask_of,
        )


class _Canvas:
    """A character grid with mask-aware line merging."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.cells: list[list[str]] = [[" "] * width for _ in range(height)]

    def get(self, x: int, y: int) -> str:
        if 0 <= y < self.height and 0 <= x < self.width:
            return self.cells[y][x]
        return ""

    def set(self, x: int, y: int, ch: str) -> None:
        if 0 <= y < self.height and 0 <= x < self.width:
            self.cells[y][x] = ch

    def merge(self, x: int, y: int, ch: str, mask: int, cs: _CharSet) -> None:
        """Place ``ch`` (contributing directions ``mask``) at (x, y).

        Cells are merged by OR-ing connection masks, so a vertical over a
        horizontal yields ``┬``/``┴`` and two crossing lines yield ``┼``.
        Opaque cells (box frames, labels, arrowheads) are never clobbered.
        """
        if not (0 <= y < self.height and 0 <= x < self.width):
            return
        cur = self.cells[y][x]
        if cur == " ":
            # Empty cell: use the glyph for this segment's own mask, so a
            # corner mask yields a corner glyph, not a bare line char.
            self.cells[y][x] = cs.join.get(mask, ch)
            return
        if cur == ch:
            return
        m_cur = cs.mask_of.get(cur)
        if m_cur is None:
            return
        self.cells[y][x] = cs.join.get(m_cur | mask, cur)

    def hline(self, x1: int, x2: int, y: int, hch: str, cs: _CharSet) -> None:
        if x1 > x2:
            return
        for x in range(x1, x2 + 1):
            self.merge(x, y, hch, L | R, cs)

    def vline(self, y1: int, y2: int, x: int, vch: str, cs: _CharSet) -> None:
        if y1 > y2:
            return
        for y in range(y1, y2 + 1):
            self.merge(x, y, vch, U | D, cs)

    def row_clear(self, x1: int, x2: int, y: int) -> bool:
        for x in range(min(x1, x2), max(x1, x2) + 1):
            if self.get(x, y) != " ":
                return False
        return True

    def col_clear(self, y1: int, y2: int, x: int) -> bool:
        for y in range(min(y1, y2), max(y1, y2) + 1):
            if self.get(x, y) != " ":
                return False
        return True

    def put_label(self, x0: int, x1: int, y: int, text: str) -> None:
        """Center ``text`` in [x0, x1] on row y, overwriting (truncating)."""
        width = x1 - x0 + 1
        if width < 1:
            return
        if len(text) > width:
            text = text[:width]
        start = max(x0, (x0 + x1) // 2 - len(text) // 2)
        for i, ch in enumerate(text):
            self.set(start + i, y, ch)

    def grow(self, width: int, height: int) -> None:
        """Extend right/down, keeping existing content."""
        if width <= self.width:
            height_only = height
        else:
            height_only = height
            for row in self.cells:
                row.extend(" " * (width - self.width))
            self.width = width
        if height_only > self.height:
            self.cells.extend([[" "] * self.width for _ in range(height_only - self.height)])
            self.height = height_only

    def text(self) -> str:
        return "\n".join("".join(row).rstrip() for row in self.cells)


def _apply_color(cv: _Canvas, pos: dict, graph: Graph) -> None:
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
            row = cv.cells[y0 + r]
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


def _comp_edges(comp: list[str], graph: Graph) -> list[Edge]:
    comp_set = set(comp)
    return [e for e in graph.edges if e.source in comp_set and e.target in comp_set]


def _layers(comp: list[str], graph: Graph) -> list[list[str]]:
    """Longest-path layering: rank[v] = 1 + max(rank[u]) over edges u->v."""
    rank = {n: 0 for n in comp}
    edges = [e for e in _comp_edges(comp, graph) if e.source != e.target]
    for _ in range(len(comp)):  # longest path needs at most len-1 passes
        changed = False
        for e in edges:
            if rank[e.target] <= rank[e.source]:
                rank[e.target] = rank[e.source] + 1
                changed = True
        if not changed:
            break
    by_rank: dict[int, list[str]] = {}
    for n in comp:
        by_rank.setdefault(rank[n], []).append(n)
    return [by_rank[r] for r in sorted(by_rank)]


def _barycenter_order(layers: list[list[str]], graph: Graph) -> list[list[str]]:
    """Reorder nodes within each layer to reduce edge crossings.

    Sugiyama barycenter heuristic: each node's x position is the average of
    its neighbours' positions in the adjacent layer; layers are then sorted
    by that average. Iterates top-down then bottom-up until stable.
    """
    order = [list(layer) for layer in layers]
    all_nodes: set[str] = {n for layer in layers for n in layer}
    adj: dict[str, list[str]] = {n: [] for n in all_nodes}
    for e in graph.edges:
        if e.source in adj and e.target in adj:
            adj[e.source].append(e.target)
            adj[e.target].append(e.source)
    n_layers = len(order)
    for _ in range(n_layers + 1):
        changed = False
        for direction in (1, -1):
            for li in range(n_layers):
                prev_i = li - direction
                if prev_i < 0 or prev_i >= n_layers:
                    continue
                prev_idx = {n: i for i, n in enumerate(order[prev_i])}
                score: list[tuple[float, int, str]] = []
                for j, n in enumerate(order[li]):
                    neigh = [x for x in adj[n] if x in prev_idx]
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


@dataclass
class _Route:
    """Planned geometry for one edge."""

    edge: Edge
    kind: str  # straight | backstraight | adjacentz | spanz | backz | detour | selfloop
    detour_y: int = 0
    x_exit: int | None = None  # exit column for back-edge detours


def _plan_routes(
    cv: _Canvas,
    pos: dict[str, tuple[int, int, int, int]],
    edges: list[Edge],
    layer_of: dict[str, int],
    n_cols: int,
    colx: list[int],
    col_w: list[int],
    pad: int,
    base_w: int,
) -> list[_Route]:
    """Choose a collision-free route per edge against the box-only canvas.

    Edges that cannot be drawn inside the base area get their own detour row
    below it. Routes are returned in graph order.
    """
    routes: list[_Route] = []
    detour_y = cv.height
    for e in edges:
        if e.source == e.target:
            routes.append(_Route(e, "selfloop"))
            continue
        s, t = layer_of[e.source], layer_of[e.target]
        sx0, sy0, sw, sh = pos[e.source]
        tx0, ty0, tw, th = pos[e.target]
        sx, tx, txr = sx0 + sw, tx0, tx0 + tw
        sy_mid, ty_mid = sy0 + sh // 2, ty0 + th // 2
        if t == s + 1:
            if sy_mid == ty_mid:
                routes.append(_Route(e, "straight"))
            else:
                routes.append(_Route(e, "adjacentz"))
            continue
        if sy_mid == ty_mid:
            span = (txr, sx - 1) if t < s else (sx, tx - 1)
            if cv.row_clear(*span, sy_mid):
                routes.append(_Route(e, "straight" if t > s else "backstraight"))
                continue
        if t > s + 1:
            cx_s = colx[s] + col_w[s] + _CHANNEL // 2
            if cv.row_clear(cx_s, tx - 1, ty_mid):
                routes.append(_Route(e, "spanz"))
            else:
                routes.append(_Route(e, "detour", detour_y))
                detour_y += 1
            continue
        # Back edge (target in an earlier layer).
        if s < n_cols - 1:
            cx_s = colx[s] + col_w[s] + _CHANNEL // 2
            if cv.row_clear(txr + 1, cx_s - 1, ty_mid):
                routes.append(_Route(e, "backz"))
            else:
                routes.append(_Route(e, "detour", detour_y, x_exit=cx_s))
                detour_y += 1
        elif pad:
            # Source in the last column: detour through the right pad column.
            routes.append(_Route(e, "detour", detour_y, x_exit=base_w - pad))
            detour_y += 1
        else:
            # No free column: exit below the source's centre column (may
            # have to cross a box below the source — degrades to a gap
            # there, never to a clobbered box).
            routes.append(_Route(e, "detour", detour_y, x_exit=sx0 + sw // 2))
            detour_y += 1
    return routes


def _get_arrows(cs: _CharSet, e: Edge) -> tuple[str, str, str]:
    """Get arrowhead characters, respecting 'arrowshape: plain'."""
    if e.attrs.get("arrowshape") == "plain":
        return (">", "<", "^")
    return (cs.ar, cs.al, cs.ar_up)


def _draw_straight(
    cv: _Canvas,
    e: Edge,
    cs: _CharSet,
    x1: int,
    x2: int,
    y: int,
    label_x0: int,
    label_x1: int,
    back: bool = False,
) -> None:
    """One horizontal run across free cells ``x1..x2`` (inclusive).

    For forward edges the source sits left of ``x1`` and the target right of
    ``x2``; for back edges it is the other way round. Arrowheads point at
    their node, the label floats on the row above the line.
    """
    hch, _vch, _cch = cs.styles[e.style or _STYLE_DEFAULT]
    ar, al, _ar_up = _get_arrows(cs, e)
    arrow_left = e.directed_to_target if back else e.directed_from_source
    arrow_right = e.directed_from_source if back else e.directed_to_target
    lo = x1 + (1 if arrow_left else 0)
    hi = x2 - (1 if arrow_right else 0)
    if lo <= hi:
        cv.hline(lo, hi, y, hch, cs)
    if arrow_left:
        cv.set(x1, y, al)
    if arrow_right:
        cv.set(x2, y, ar)
    if e.label:
        ly = y - 1 if y > 0 else y + 1
        cv.put_label(label_x0, label_x1, ly, e.label)


def _draw_z(
    cv: _Canvas,
    e: Edge,
    cs: _CharSet,
    *,
    sx: int,
    y1: int,
    cx: int,
    tx_border: int,
    y2: int,
    label_x0: int,
    label_x1: int,
    label_y: int,
    back: bool = False,
) -> None:
    """Orthogonal Z route: right along row y1, vertical at cx, then row y2.

    ``tx_border`` is the target's left border (forward) or right border
    (back) x position. Falls back to a straight run when y1 == y2.
    """
    if y1 == y2:
        if back:
            _draw_straight(
                cv, e, cs, tx_border, sx - 1, y1, label_x0, label_x1, back=True
            )
        else:
            _draw_straight(cv, e, cs, sx, tx_border - 1, y1, label_x0, label_x1)
        return
    hch, vch, _cch = cs.styles[e.style or _STYLE_DEFAULT]
    ar, al, _ar_up = _get_arrows(cs, e)
    down = y2 > y1
    cv.hline(sx, cx - 1, y1, hch, cs)
    cv.merge(cx, y1, hch, L | (D if down else U), cs)
    cv.vline(min(y1, y2) + 1, max(y1, y2) - 1, cx, vch, cs)
    if back:
        cv.merge(cx, y2, vch, (U if down else D) | L, cs)
        cv.hline(tx_border + 1, cx - 1, y2, hch, cs)
        if e.directed_to_target:
            cv.set(tx_border, y2, al)
    else:
        cv.merge(cx, y2, vch, (U if down else D) | R, cs)
        cv.hline(cx + 1, tx_border - 2, y2, hch, cs)
        if e.directed_to_target:
            cv.set(tx_border - 1, y2, ar)
    if e.directed_from_source:
        cv.set(sx, y1, al)
    if e.label:
        ly = label_y if label_y >= 0 else y1 + 1
        cv.put_label(label_x0, label_x1, ly, e.label)


def _draw_detour(
    cv: _Canvas,
    route: _Route,
    cs: _CharSet,
    pos: dict[str, tuple[int, int, int, int]],
    col_s: int,
    col_t: int,
    colx: list[int],
    col_w: list[int],
) -> None:
    """Route an edge through its reserved detour row below the diagram."""
    e = route.edge
    hch, vch, _cch = cs.styles[e.style or _STYLE_DEFAULT]
    ar, al, ar_up = _get_arrows(cs, e)
    r = route.detour_y
    sx0, sy0, sw, sh = pos[e.source]
    tx0, ty0, tw, th = pos[e.target]
    sx, tx, txr = sx0 + sw, tx0, tx0 + tw
    sy_exit = sy0 + sh - 1
    ty_mid = ty0 + th // 2
    back = col_t < col_s
    if back:
        # Down in a free column, left along the detour row, up into the
        # channel right of the target column, left into its right border.
        x_exit = route.x_exit if route.x_exit is not None else sx0 + sw // 2
        cx_t = colx[col_t] + col_w[col_t] + _CHANNEL // 2
        if x_exit >= sx:
            cv.hline(sx, x_exit - 1, sy_exit, hch, cs)
            cv.merge(x_exit, sy_exit, hch, L | D, cs)
        cv.vline(sy_exit + 1, r - 1, x_exit, vch, cs)
        cv.merge(x_exit, r, hch, U | L, cs)
        cv.hline(cx_t + 1, x_exit - 1, r, hch, cs)
        cv.merge(cx_t, r, hch, R | U, cs)
        cv.vline(ty_mid + 1, r - 1, cx_t, vch, cs)
        cv.merge(cx_t, ty_mid, vch, D | L, cs)
        cv.hline(txr + 1, cx_t - 1, ty_mid, hch, cs)
        if e.directed_to_target:
            cv.set(txr, ty_mid, al)
        if e.directed_from_source:
            if x_exit >= sx:
                cv.set(sx, sy_exit, al)
            else:
                cv.set(x_exit, sy_exit + 1, ar_up)
        if e.label:
            cv.put_label(cx_t + 1, x_exit - 1, r, e.label)
    else:
        # Down in the channel right of the source column, right along the
        # detour row, up into the channel left of the target column.
        x_exit = colx[col_s] + col_w[col_s] + _CHANNEL // 2
        cx_t = colx[col_t - 1] + col_w[col_t - 1] + _CHANNEL // 2
        cv.hline(sx, x_exit - 1, sy_exit, hch, cs)
        cv.merge(x_exit, sy_exit, hch, L | D, cs)
        cv.vline(sy_exit + 1, r - 1, x_exit, vch, cs)
        cv.merge(x_exit, r, hch, U | R, cs)
        cv.hline(x_exit + 1, cx_t - 1, r, hch, cs)
        cv.merge(cx_t, r, hch, L | U, cs)
        cv.vline(ty_mid + 1, r - 1, cx_t, vch, cs)
        cv.merge(cx_t, ty_mid, vch, D | R, cs)
        cv.hline(cx_t + 1, tx - 2, ty_mid, hch, cs)
        if e.directed_to_target:
            cv.set(tx - 1, ty_mid, ar)
        if e.directed_from_source:
            cv.set(sx, sy_exit, al)
        if e.label:
            cv.put_label(x_exit + 1, cx_t - 1, r, e.label)


def _draw_selfloop(
    cv: _Canvas,
    e: Edge,
    cs: _CharSet,
    pos: dict[str, tuple[int, int, int, int]],
    col_of: dict[str, int],
    col_w: list[int],
    colx: list[int],
) -> None:
    """Small loop leaving the node's right side and re-entering below."""
    hch, vch, _cch = cs.styles[e.style or _STYLE_DEFAULT]
    _ar, al, ar_up = _get_arrows(cs, e)
    x0, y0, w, h = pos[e.source]
    mid = y0 + h // 2
    gap_row = y0 + h  # spare gap row reserved in the layout
    x_exit = x0 + w
    x_arrow = x0 + w // 2
    # Loop column: first free column between the box and the next layer
    # (the gutter is always box-free; falls back to the default column).
    c = col_of[e.source]
    col_end = colx[c] + col_w[c] - 1
    x_loop = x0 + w + 1
    for x in range(x0 + w + 1, col_end + 1):
        if cv.col_clear(mid + 1, gap_row - 1, x):
            x_loop = x
            break
    cv.merge(x_exit, mid, hch, L | R, cs)
    cv.merge(x_loop, mid, vch, L | D, cs)
    cv.vline(mid + 1, gap_row - 1, x_loop, vch, cs)
    cv.merge(x_loop, gap_row, hch, U | L, cs)
    cv.hline(x_arrow + 1, x_loop - 1, gap_row, hch, cs)
    cv.set(x_arrow, gap_row, ar_up)
    if e.directed_from_source:
        cv.set(x_exit, mid, al)
    if e.label:
        cv.put_label(x0, x0 + w, gap_row + 1, e.label)


def render(graph: Graph, *, ascii_style: bool = False, color: bool = False) -> str:
    """Render the graph to multi-line ASCII/Unicode text (no trailing newline)."""
    if not graph.nodes:
        return ""
    cs = _CharSet.make(ascii_style)
    bands: list[str] = []
    for comp in _components(graph):
        layers = _barycenter_order(_layers(comp, graph), graph)
        layer_boxes = [
            [_box(graph.nodes[n], cs.box) for n in layer] for layer in layers
        ]

        # Self-loop nodes reserve one extra gap row below their box.
        selfloop: set[str] = set()
        for e in graph.edges:
            if e.source == e.target and e.source in comp:
                selfloop.add(e.source)

        col_w = [
            max(max(len(row) for row in b) for b in boxes) for boxes in layer_boxes
        ]
        col_h = [
            sum(len(b) + (1 if n in selfloop else 0)
                for b, n in zip(boxes, layers[c], strict=True))
            + (len(boxes) - 1)
            for c, boxes in enumerate(layer_boxes)
        ]
        y_offs: list[list[int]] = []
        for c, boxes in enumerate(layer_boxes):
            offs: list[int] = []
            y = 0
            for b, n in zip(boxes, layers[c], strict=True):
                offs.append(y)
                y += len(b) + 1 + (1 if n in selfloop else 0)
            y_offs.append(offs)

        has_groups = any(graph.nodes[n].attrs.get("group") for n in comp)
        pad = 1 if has_groups else 0
        base_h = (max(col_h) if col_h else 0) + 2 * pad

        colx: list[int] = []
        x = pad
        for w in col_w:
            colx.append(x)
            x += w + _CHANNEL
        base_w = x - _CHANNEL + pad

        cv = _Canvas(base_w, base_h)
        pos: dict[str, tuple[int, int, int, int]] = {}
        for c, boxes in enumerate(layer_boxes):
            for i, b in enumerate(boxes):
                x0, y0 = colx[c], y_offs[c][i] + pad
                for r, row in enumerate(b):
                    for cc, ch in enumerate(row):
                        cv.cells[y0 + r][x0 + cc] = ch
                pos[layers[c][i]] = (x0, y0, len(b[0]), len(b))

        edges = _comp_edges(comp, graph)
        layer_of = {n: c for c, layer in enumerate(layers) for n in layer}
        routes = _plan_routes(
            cv, pos, edges, layer_of, len(layers), colx, col_w, pad, base_w
        )

        # Grow the canvas for detour rows and wide self loops.
        width = base_w
        for route in routes:
            if route.kind == "selfloop":
                x0, _y0, w, _h = pos[route.edge.source]
                width = max(width, x0 + w + 2)
        height = max(base_h, max((rt.detour_y for rt in routes), default=base_h - 1) + 1)
        cv.grow(width, height)

        for route in routes:
            e = route.edge
            sx0, sy0, sw, sh = pos[e.source]
            tx0, ty0, tw, th = pos[e.target]
            sx, tx = sx0 + sw, tx0
            sy_mid, ty_mid = sy0 + sh // 2, ty0 + th // 2
            sy_exit = sy0 + sh - 1
            s, t = layer_of[e.source], layer_of[e.target]
            if route.kind == "selfloop":
                _draw_selfloop(cv, e, cs, pos, layer_of, col_w, colx)
            elif route.kind == "straight":
                _draw_straight(
                    cv, e, cs, sx, tx - 1, sy_mid, sx, min(tx - 1, colx[s + 1] - 1)
                )
            elif route.kind == "backstraight":
                _draw_straight(
                    cv,
                    e,
                    cs,
                    tx0 + tw,
                    sx - 1,
                    ty_mid,
                    tx0 + tw,
                    min(colx[t + 1] - 1, sx - 1),
                    back=True,
                )
            elif route.kind == "adjacentz":
                cx = (sx + tx) // 2 if tx - sx > _CHANNEL else sx + _CHANNEL // 2
                _draw_z(
                    cv, e, cs,
                    sx=sx, y1=sy_exit, cx=cx, tx_border=tx, y2=ty_mid,
                    label_x0=sx, label_x1=colx[s + 1] - 1, label_y=sy_exit - 1,
                )
            elif route.kind == "spanz":
                cx_s = colx[s] + col_w[s] + _CHANNEL // 2
                _draw_z(
                    cv, e, cs,
                    sx=sx, y1=sy_exit, cx=cx_s, tx_border=tx, y2=ty_mid,
                    label_x0=sx, label_x1=colx[s + 1] - 1, label_y=sy_exit - 1,
                )
            elif route.kind == "backz":
                cx_s = colx[s] + col_w[s] + _CHANNEL // 2
                _draw_z(
                    cv, e, cs,
                    sx=sx, y1=sy_exit, cx=cx_s, tx_border=tx0 + tw, y2=ty_mid,
                    label_x0=tx0 + tw, label_x1=colx[t + 1] - 1,
                    label_y=ty_mid - 1, back=True,
                )
            else:
                _draw_detour(cv, route, cs, pos, s, t, colx, col_w)

        _draw_groups(cv, pos, graph, cs.box)
        if color:
            _apply_color(cv, pos, graph)
        bands.append(cv.text())
    return "\n\n".join(bands)


@dataclass
class _GroupFrame:
    """One (possibly merged) group frame: label, members and bounding box."""

    label: str
    members: set[str]
    box: tuple[int, int, int, int]


def _draw_groups(
    cv: _Canvas,
    pos: dict[str, tuple[int, int, int, int]],
    graph: Graph,
    box: _BoxChars,
) -> None:
    """Draw a labelled frame around each group's nodes.

    Groups whose bounding boxes overlap (shared nodes) are merged into a
    single combined frame with a combined label.
    """
    by_group: dict[str, list[str]] = {}
    for n in graph.nodes:
        grp = graph.nodes[n].attrs.get("group")
        if grp and n in pos:
            for g in grp.split(","):
                by_group.setdefault(g, []).append(n)

    def bbox(members: set[str]) -> tuple[int, int, int, int]:
        xs = [pos[m][0] for m in members]
        ys = [pos[m][1] for m in members]
        xe = [pos[m][0] + pos[m][2] for m in members]
        ye = [pos[m][1] + pos[m][3] for m in members]
        x0, x1 = max(min(xs) - 1, 0), min(max(xe) + 1, cv.width - 1)
        y0, y1 = max(min(ys) - 1, 0), min(max(ye) + 1, cv.height - 1)
        return x0, y0, x1, y1

    def overlap(
        a: tuple[int, int, int, int], b: tuple[int, int, int, int]
    ) -> bool:
        return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])

    frames: list[_GroupFrame] = []
    for grp, members in by_group.items():
        new_box = bbox(set(members))
        for frame in frames:
            if overlap(new_box, frame.box):
                frame.label += f" | {grp}"
                frame.members |= set(members)
                # The bounding box of a union equals the union of the
                # (clamped) bounding boxes, so combine directly.
                frame.box = (
                    min(frame.box[0], new_box[0]),
                    min(frame.box[1], new_box[1]),
                    max(frame.box[2], new_box[2]),
                    max(frame.box[3], new_box[3]),
                )
                break
        else:
            frames.append(_GroupFrame(label=grp, members=set(members), box=new_box))

    tl, tr, bl, br, v, h = box
    for frame in frames:
        x0, y0, x1, y1 = frame.box
        for x in range(x0, x1 + 1):
            if cv.cells[y0][x] == " ":
                cv.cells[y0][x] = h
            if cv.cells[y1][x] == " ":
                cv.cells[y1][x] = h
        for y in range(y0, y1 + 1):
            if cv.cells[y][x0] == " ":
                cv.cells[y][x0] = v
            if cv.cells[y][x1] == " ":
                cv.cells[y][x1] = v
        cv.cells[y0][x0], cv.cells[y0][x1] = tl, tr
        cv.cells[y1][x0], cv.cells[y1][x1] = bl, br
        label = f" {frame.label} "
        for i, ch in enumerate(label):
            if x0 + 1 + i <= x1:
                cv.cells[y0][x0 + 1 + i] = ch
