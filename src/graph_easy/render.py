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

from graph_easy._width import display_width, truncate_display
from graph_easy.node import Node
from graph_easy.parser import Edge, Graph

_CHANNEL = 5
_STYLE_DEFAULT = "solid"

# Sentinel stored in the *second* display column of a wide (CJK/emoji)
# character. It lets the grid be indexed by display column while the glyph
# lives only at the first column; ``text()`` drops it so the wide char still
# renders at its true width but occupies two grid columns.
_WIDE_CONT = "\x00"

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
    L | R | U: "┴",
    L | R | D: "┬",
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
# Named colours map to classic SGR codes; ``#RRGGBB``/``#RGB`` map to
# 24-bit true-colour. See ``_fg_sgr``/``_bg_sgr``.
_ANSI_FG: dict[str, str] = {
    "black": "30",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "white": "37",
    "brightred": "91",
    "brightgreen": "92",
    "brightyellow": "93",
    "brightblue": "94",
    "brightmagenta": "95",
    "brightcyan": "96",
    "grey": "90",
    "gray": "90",
    "brightwhite": "97",
}
_ANSI_BG: dict[str, str] = {
    "black": "40",
    "red": "41",
    "green": "42",
    "yellow": "43",
    "blue": "44",
    "magenta": "45",
    "cyan": "46",
    "white": "47",
    "brightred": "101",
    "brightgreen": "102",
    "brightyellow": "103",
    "brightblue": "104",
    "brightmagenta": "105",
    "brightcyan": "106",
    "grey": "100",
    "gray": "100",
    "brightwhite": "107",
}

_ASSOC_NAMES: dict[str, tuple[int, int, int]] = {
    "navy": (0, 0, 128),
    "darkblue": (0, 0, 139),
    "blue": (0, 0, 255),
    "mediumblue": (0, 0, 205),
    "royalblue": (65, 105, 225),
    "steelblue": (70, 130, 180),
    "cornflowerblue": (100, 149, 237),
    "dodgerblue": (30, 144, 255),
    "deepskyblue": (0, 191, 255),
    "lightskyblue": (135, 206, 250),
    "lightblue": (173, 216, 230),
    "skyblue": (135, 206, 235),
    "teal": (0, 128, 128),
    "darkcyan": (0, 139, 139),
    "cyan": (0, 255, 255),
    "turquoise": (64, 224, 208),
    "darkgreen": (0, 100, 0),
    "green": (0, 128, 0),
    "forestgreen": (34, 139, 34),
    "limegreen": (50, 205, 50),
    "lime": (0, 255, 0),
    "seagreen": (46, 139, 87),
    "olive": (128, 128, 0),
    "darkgoldenrod": (184, 134, 11),
    "olivedrab": (107, 142, 35),
    "yellow": (255, 255, 0),
    "gold": (255, 215, 0),
    "orange": (255, 165, 0),
    "darkorange": (255, 140, 0),
    "orangered": (255, 69, 0),
    "maroon": (128, 0, 0),
    "darkred": (139, 0, 0),
    "red": (255, 0, 0),
    "firebrick": (178, 34, 34),
    "crimson": (220, 20, 60),
    "indianred": (205, 92, 92),
    "pink": (255, 192, 203),
    "hotpink": (255, 105, 180),
    "deeppink": (255, 20, 147),
    "magenta": (255, 0, 255),
    "purple": (128, 0, 128),
    "darkorchid": (153, 50, 204),
    "violet": (238, 130, 238),
    "plum": (221, 160, 221),
    "orchid": (218, 112, 214),
    "brown": (165, 42, 42),
    "saddlebrown": (139, 69, 19),
    "chocolate": (210, 105, 30),
    "peru": (205, 133, 63),
    "sienna": (160, 82, 45),
    "tan": (210, 180, 140),
    "silver": (192, 192, 192),
    "gray": (128, 128, 128),
    "grey": (128, 128, 128),
    "slategray": (112, 128, 144),
    "dimgray": (105, 105, 105),
    "white": (255, 255, 255),
    "snow": (255, 250, 250),
    "lightgray": (211, 211, 211),
    "aliceblue": (240, 248, 255),
    "beige": (245, 245, 220),
    "ivory": (255, 255, 240),
    "cornsilk": (255, 248, 220),
    "wheat": (245, 222, 179),
    "khaki": (240, 230, 140),
    "goldenrod": (218, 165, 32),
    "salmon": (250, 128, 114),
    "coral": (255, 127, 80),
    "tomato": (255, 99, 71),
    "lavender": (230, 230, 250),
}

# ColourBrewer palettes (subset of the most common sequential / diverging /
# qualitative schemes), used via ``color: <index>; scheme: <name><n>``.
# Each value is a list of (r, g, b) triples indexed from 1.
_BREWER: dict[str, tuple[tuple[int, int, int], ...]] = {
    "blues3": ((222, 235, 247), (158, 202, 225), (49, 130, 189)),
    "blues5": ((239, 243, 255), (189, 215, 231), (107, 174, 214), (49, 130, 189), (8, 81, 156)),
    "greens3": ((229, 245, 224), (161, 217, 155), (49, 163, 84)),
    "greens5": ((237, 248, 233), (186, 228, 179), (116, 196, 118), (49, 163, 84), (0, 109, 44)),
    "oranges3": ((254, 230, 206), (253, 174, 107), (230, 85, 13)),
    "oranges5": ((254, 237, 222), (253, 190, 133), (253, 141, 60), (230, 85, 13), (166, 54, 3)),
    "purples3": ((239, 237, 245), (188, 189, 220), (117, 107, 177)),
    "purples5": ((242, 240, 247), (203, 201, 226), (158, 154, 200), (117, 107, 177), (84, 39, 143)),
    "reds3": ((254, 224, 210), (252, 146, 114), (222, 45, 38)),
    "reds5": ((254, 229, 217), (252, 174, 145), (251, 106, 74), (222, 45, 38), (165, 0, 38)),
    "greys3": ((240, 240, 240), (189, 189, 189), (99, 99, 99)),
    "greys5": ((247, 247, 247), (204, 204, 204), (150, 150, 150), (99, 99, 99), (37, 37, 37)),
    "rdbu3": ((239, 138, 98), (247, 247, 247), (103, 169, 207)),
    "rdbu5": ((202, 0, 32), (244, 165, 130), (247, 247, 247), (146, 197, 222), (5, 113, 176)),
    "piyg3": ((233, 163, 201), (247, 247, 247), (161, 215, 106)),
    "piyg5": ((208, 28, 139), (241, 182, 218), (247, 247, 247), (184, 225, 134), (77, 172, 38)),
    "brbg3": ((216, 179, 101), (245, 245, 245), (90, 180, 172)),
    "brbg5": ((166, 97, 26), (223, 194, 125), (245, 245, 245), (128, 205, 193), (1, 133, 113)),
    "set1": (
        (228, 26, 28),
        (55, 126, 184),
        (77, 175, 74),
        (152, 78, 163),
        (255, 127, 0),
        (255, 255, 51),
        (166, 86, 40),
        (247, 129, 191),
        (153, 153, 153),
    ),
    "set2": (
        (102, 194, 165),
        (252, 141, 98),
        (141, 160, 203),
        (231, 138, 195),
        (166, 216, 84),
        (255, 217, 47),
        (229, 196, 148),
        (179, 179, 179),
    ),
    "set3": (
        (141, 211, 199),
        (255, 255, 179),
        (190, 186, 218),
        (251, 128, 114),
        (128, 177, 211),
        (253, 180, 98),
        (179, 222, 105),
        (252, 205, 229),
        (217, 217, 217),
    ),
    "paired": (
        (166, 206, 227),
        (31, 120, 180),
        (178, 223, 138),
        (51, 160, 44),
        (251, 154, 153),
        (227, 26, 28),
        (253, 191, 111),
        (255, 127, 0),
        (202, 178, 214),
        (106, 61, 154),
        (255, 255, 153),
        (177, 89, 40),
    ),
    "accent": (
        (127, 201, 127),
        (190, 174, 212),
        (253, 192, 134),
        (255, 255, 153),
        (56, 108, 176),
        (240, 2, 127),
        (191, 91, 23),
        (102, 102, 102),
    ),
    "dark2": (
        (27, 158, 119),
        (217, 95, 2),
        (117, 112, 179),
        (231, 41, 138),
        (102, 166, 30),
        (230, 171, 2),
        (166, 118, 29),
        (102, 102, 102),
    ),
}


class _ColorError(ValueError):
    """Raised for an unrecognised colour value."""


def _parse_rgb(value: str) -> tuple[int, int, int]:
    """Resolve a colour value to an (r, g, b) triple.

    Accepts ``#RRGGBB``, ``#RGB`` shorthand, a named colour from the extended
    table, or one of the 16 classic ANSI colour names. Returns the triple.
    """
    v = value.strip().lower()
    if v.startswith("#"):
        hexs = v[1:]
        if len(hexs) == 3:
            hexs = "".join(c * 2 for c in hexs)
        if len(hexs) != 6 or not all(c in "0123456789abcdef" for c in hexs):
            raise _ColorError(f"invalid hex colour {value!r}")
        return tuple(int(hexs[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    if v in _ASSOC_NAMES:
        return _ASSOC_NAMES[v]
    named = {
        "black": (0, 0, 0),
        "red": (255, 0, 0),
        "green": (0, 128, 0),
        "yellow": (255, 255, 0),
        "blue": (0, 0, 255),
        "magenta": (255, 0, 255),
        "cyan": (0, 255, 255),
        "white": (255, 255, 255),
        "grey": (128, 128, 128),
        "gray": (128, 128, 128),
    }
    if v in named:
        return named[v]
    raise _ColorError(f"unknown colour {value!r}")


def _resolve_rgb(value: str, scheme: str | None = None) -> tuple[int, int, int]:
    """Resolve a colour to (r, g, b), honouring a ColourBrewer ``scheme``.

    ``scheme`` is used only when ``value`` is a 1-based index into a Brewery
    palette (e.g. ``color: 3; scheme: blues5``). Otherwise falls back to the
    named / hex parsing in :func:`_parse_rgb`.
    """
    v = value.strip().lower()
    if scheme and (v.isdigit() or v.startswith("#")):
        key = scheme.strip().lower()
        if key in _BREWER and v.isdigit():
            idx = int(v)
            pal = _BREWER[key]
            if 1 <= idx <= len(pal):
                return pal[idx - 1]
    return _parse_rgb(value)


def _fg_sgr(name: str, scheme: str | None = None) -> str:
    """Return the SGR parameter string for a foreground colour ('' if unknown)."""
    v = name.strip().lower()
    if v in _ANSI_FG:
        return _ANSI_FG[v]
    try:
        r, g, b = _resolve_rgb(v, scheme)
    except _ColorError:
        return ""
    return f"38;2;{r};{g};{b}"


def _bg_sgr(name: str, scheme: str | None = None) -> str:
    """Return the SGR parameter string for a background colour ('' if unknown)."""
    v = name.strip().lower()
    if v in _ANSI_BG:
        return _ANSI_BG[v]
    try:
        r, g, b = _resolve_rgb(v, scheme)
    except _ColorError:
        return ""
    return f"48;2;{r};{g};{b}"


_TEXT_STYLES: dict[str, str] = {
    "bold": "1",
    "italic": "3",
    "underline": "4",
    "strike": "9",
}


def _text_style_sgr(style: str) -> str:
    """Return the SGR parameter for a text style ('' if unknown)."""
    v = style.strip().lower().replace("-", "")
    if v in _TEXT_STYLES:
        return _TEXT_STYLES[v]
    return ""


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
        # Set of (x, y) cells occupied by a node's box border. Border cells
        # are opaque to line drawing: a wire must never overwrite or merge
        # with a box frame, or it would punch through (e.g. turn a ─ border
        # into ┼) and fabricate an edge.
        self.border: set[tuple[int, int]] = set()

    def get(self, x: int, y: int) -> str:
        if 0 <= y < self.height and 0 <= x < self.width:
            ch = self.cells[y][x]
            return "" if ch == _WIDE_CONT else ch
        return ""

    def set(self, x: int, y: int, ch: str) -> None:
        """Place ``ch`` at (x, y), claiming its full display width.

        A wide (CJK/emoji) character occupies two display columns, so the
        nested column is marked with ``_WIDE_CONT`` to reserve it and keep
        later writes from clobbering the continuation column.
        """
        if not (0 <= y < self.height and 0 <= x < self.width):
            return
        self.cells[y][x] = ch
        w = display_width(ch)
        if w == 2 and 0 <= y < self.height and x + 1 < self.width:
            self.cells[y][x + 1] = _WIDE_CONT

    def merge(self, x: int, y: int, ch: str, mask: int, cs: _CharSet) -> None:
        """Place ``ch`` (contributing directions ``mask``) at (x, y).

        Cells are merged by OR-ing connection masks, so a vertical over a
        horizontal yields ``┬``/``┴`` and two crossing lines yield ``┼``.
        Opaque cells (box frames, labels, arrowheads) are never clobbered.
        """
        if not (0 <= y < self.height and 0 <= x < self.width):
            return
        # Box borders are opaque: a line must never merge with (and thus
        # punch through) a node's frame. The border is drawn/owned by the
        # box; an edge reaches it via the arrowhead placed just outside.
        if (x, y) in self.border:
            return
        cur = self.cells[y][x]
        if cur == " " or cur == _WIDE_CONT:
            # Empty cell: use the glyph for this segment's own mask, so a
            # corner mask yields a corner glyph, not a bare line char. A
            # wide-char continuation column is left untouched so a line
            # never splits a CJK glyph in half.
            if cur == " ":
                self.cells[y][x] = cs.join.get(mask, ch)
            return

        # A corner joining an existing line must add its vertical connection
        # even when the glyphs match; otherwise the junction collapses to a
        # bare line char (e.g. a ┴/┬ merge lost under an existing ─).
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
        tw = display_width(text)
        if tw > width:
            text = truncate_display(text, width)
            tw = display_width(text)
        start = max(x0, (x0 + x1) // 2 - tw // 2)
        for ch in text:
            self.set(start, y, ch)
            start += display_width(ch)

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
        lines: list[str] = []
        for row in self.cells:
            out = "".join(ch for ch in row if ch != _WIDE_CONT)
            lines.append(out.rstrip())
        return "\n".join(lines)


def _apply_color(cv: _Canvas, pos: dict, graph: Graph) -> None:
    """Post-process: wrap node interiors/borders in ANSI colour codes.

    ``color`` sets the text foreground, ``fill`` the background, and
    ``border-color`` the box frame (all three accept named or ``#RRGGBB``
    values). Colour codes are injected around the relevant characters so
    the box grid stays valid.
    """
    for name, (x0, y0, w, h) in pos.items():
        node = graph.nodes[name]
        scheme = node.attrs.get("scheme") or node.attrs.get("colorscheme")
        # label text colour (foreground) + node fill (background)
        fg_codes = [
            c
            for c in (
                _bg_sgr(node.attrs.get("fill", ""), scheme),
                _fg_sgr(node.attrs.get("color", ""), scheme),
                _text_style_sgr(node.attrs.get("text-style", "")),
            )
            if c
        ]
        if fg_codes:
            start = "\x1b[" + ";".join(fg_codes) + "m"
            end = "\x1b[0m"
            for r in range(1, h - 1):
                row = cv.cells[y0 + r]
                row[x0] = start + row[x0]
                row[x0 + w - 1] += end
        # border frame colour: one escape around the whole top/bottom row.
        bd = _fg_sgr(
            node.attrs.get("border-color", node.attrs.get("bordercolor", "")),
            scheme,
        )
        if bd:
            bd_start = "\x1b[" + bd + "m"
            end = "\x1b[0m"
            for r in (y0, y0 + h - 1):
                row = cv.cells[r]
                row[x0] = bd_start + row[x0]
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
    if shape == "hexagon":
        return _box_hexagon(node, border, box)
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
    if shape in ("ellipse", "rounded", "circle", "oval"):
        tl, tr, bl, br = "╭", "╮", "╰", "╯"
    border_t = tl + h2 * (w - 2) + tr
    rows: list[str] = [border_t]
    for _ in range(pad_y):
        rows.append(v2 + " " * (w - 2) + v2)
    for line in lines:
        right = max(inner_w - display_width(line), 0)
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
            right_pad = " " * (max(inner_w - display_width(text), 0) + pad + 1)
            row = left_pad + vch + text + right_pad + vch
        rows.append(row.ljust(width))
    return rows


def _box_hexagon(node: Node, border: str, box: _BoxChars) -> list[str]:
    """Hexagon node — slanted top/bottom edges with a horizontal label band."""
    _, _, _, _, v, h = box
    hch = "═" if border == "double" else h
    vch = "║" if border == "double" else v
    lines = node.label_lines()
    inner_w = node.inner_width()
    width = inner_w + 4
    total_rows = len(lines) + 2
    rows: list[str] = []
    for r in range(total_rows):
        if r == 0:
            row = " " + "/" + hch * max(inner_w, 2) + "\\"
        elif r == total_rows - 1:
            row = " " + "\\" + hch * max(inner_w, 2) + "/"
        else:
            li = r - 1
            text = lines[li] if li < len(lines) else ""
            right = max(inner_w - display_width(text), 0)
            row = " " + vch + " " + text + " " * right + " " + vch
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
    cx: int | None = None  # bend column for adjacent-layer Z edges


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
                continue
            # Adjacent-layer Z edge: bend through the channel between the
            # source and target columns. The channel centre is box-free by
            # construction, unlike a midpoint between the source's actual
            # right edge and the target's left edge (which can land on an
            # unrelated node's border when a wide sibling shares the layer).
            cx_s = colx[s] + col_w[s] + _CHANNEL // 2
            if (
                cx_s > sx
                and cv.row_clear(sx, cx_s - 1, sy_mid)
                and cv.col_clear(min(sy_mid, ty_mid) + 1, max(sy_mid, ty_mid) - 1, cx_s)
                and cv.row_clear(cx_s + 1, tx - 1, ty_mid)
            ):
                routes.append(_Route(e, "adjacentz", cx=cx_s))
            else:
                routes.append(_Route(e, "detour", detour_y))
                detour_y += 1
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
    """Get arrowhead characters, respecting ``arrow-style``/``arrowshape``.

    ``plain``/``open``/``line`` use the ASCII ``>``/``<``/``^`` heads; anything
    else (the default, ``filled``) uses the Unicode filled triangle.
    """
    style = e.attrs.get("arrow-style", e.attrs.get("arrowshape", "filled"))
    if style in ("plain", "open", "line"):
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
            _draw_straight(cv, e, cs, tx_border, sx - 1, y1, label_x0, label_x1, back=True)
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
        y_exit = sy0 + sh // 2  # exit from the source's centre row
        cv.hline(sx, x_exit - 1, y_exit, hch, cs)
        cv.merge(x_exit, y_exit, hch, L | D, cs)
        cv.vline(y_exit + 1, r - 1, x_exit, vch, cs)
        cv.merge(x_exit, r, hch, U | R, cs)
        cv.hline(x_exit + 1, cx_t - 1, r, hch, cs)
        cv.merge(cx_t, r, hch, L | U, cs)
        cv.vline(ty_mid + 1, r - 1, cx_t, vch, cs)
        cv.merge(cx_t, ty_mid, vch, D | R, cs)
        cv.hline(cx_t + 1, tx - 2, ty_mid, hch, cs)
        if e.directed_to_target:
            cv.set(tx - 1, ty_mid, ar)
        if e.directed_from_source:
            cv.set(sx, y_exit, al)
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
        layer_boxes = [[_box(graph.nodes[n], cs.box) for n in layer] for layer in layers]

        # Self-loop nodes reserve one extra gap row below their box.
        selfloop: set[str] = set()
        for e in graph.edges:
            if e.source == e.target and e.source in comp:
                selfloop.add(e.source)

        col_w = [max(max(display_width(row) for row in b) for b in boxes) for boxes in layer_boxes]
        col_h = [
            sum(len(b) + (1 if n in selfloop else 0) for b, n in zip(boxes, layers[c], strict=True))
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
                h = len(b)
                w = display_width(b[0])
                for r, row in enumerate(b):
                    cc = 0
                    for ch in row:
                        cx = x0 + cc
                        cv.set(cx, y0 + r, ch)
                        # record opaque border ring (top/bottom cols, sides)
                        if r in (0, h - 1) or cc in (0, display_width(row) - 1):
                            cv.border.add((cx, y0 + r))
                        cc += display_width(ch)
                pos[layers[c][i]] = (x0, y0, w, h)

        edges = _comp_edges(comp, graph)
        layer_of = {n: c for c, layer in enumerate(layers) for n in layer}
        routes = _plan_routes(cv, pos, edges, layer_of, len(layers), colx, col_w, pad, base_w)

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
                _draw_straight(cv, e, cs, sx, tx - 1, sy_mid, sx, min(tx - 1, colx[s + 1] - 1))
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
                cx = route.cx if route.cx is not None else colx[s] + col_w[s] + _CHANNEL // 2
                _draw_z(
                    cv,
                    e,
                    cs,
                    sx=sx,
                    y1=sy_mid,
                    cx=cx,
                    tx_border=tx,
                    y2=ty_mid,
                    label_x0=sx,
                    label_x1=colx[s + 1] - 1,
                    label_y=sy_mid - 1,
                )
            elif route.kind == "spanz":
                cx_s = colx[s] + col_w[s] + _CHANNEL // 2
                _draw_z(
                    cv,
                    e,
                    cs,
                    sx=sx,
                    y1=sy_exit,
                    cx=cx_s,
                    tx_border=tx,
                    y2=ty_mid,
                    label_x0=sx,
                    label_x1=colx[s + 1] - 1,
                    label_y=sy_exit - 1,
                )
            elif route.kind == "backz":
                cx_s = colx[s] + col_w[s] + _CHANNEL // 2
                _draw_z(
                    cv,
                    e,
                    cs,
                    sx=sx,
                    y1=sy_exit,
                    cx=cx_s,
                    tx_border=tx0 + tw,
                    y2=ty_mid,
                    label_x0=tx0 + tw,
                    label_x1=colx[t + 1] - 1,
                    label_y=ty_mid - 1,
                    back=True,
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

    def overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
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
