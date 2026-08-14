"""Graph::Easy DSL parser — text graph language.

Faithful translation of the upstream grammar subset::

    [ node label ] --> [ other node ]
    A -> B <- C
    [ A ] -- label width 40 --> [ B ]

Supported tokens (subset of upstream ``Parser``)::

    node  := '[' label ']' | bare_word
    edge  := '<'? connector '>'?     with connector = one+ of '-' '=' '.'

    "--"    undirected            "-->"  directed to target
    "<--"   directed from target  "<-->"  bidirectional

Arbitrary repeated dashes (``--->``, ``<----`` ...) are tolerated.
Comment lines (``# ...``) are ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from graph_easy.node import Node

_TOK = re.compile(
    r"\s*"
    r"(?:"
    r"(\[[^\]]*\])"          # 1: bracketed node
    r"|(<[=.\-~#]*[=.\-~#]>?)"   # 2: edge with leading '<'
    r"|([=.\-~#]*[=.\-~#]>?)"    # 3: edge without '<'
    r"|(\{[^{}]*\})"         # 4: attribute block { k: v; }
    r"|([^\s]+)"             # 5: bare word
    r")"
)


def _parse_attrs(block: str) -> dict[str, str]:
    """Parse ``{ key: value; key2: value2; }`` into a dict (lenient)."""
    attrs: dict[str, str] = {}
    for part in block.strip("{}").split(";"):
        if ":" not in part:
            continue
        k, _, v = part.partition(":")
        k = k.strip()
        v = v.strip()
        if k:
            attrs[k] = v
    return attrs


@dataclass
class Edge:
    """Directed/undirected connection between two nodes."""

    source: str
    target: str
    label: str | None = None
    directed_to_target: bool = True  # arrow at the target ('-->')
    directed_from_source: bool = False  # arrow at the source ('<--')
    style: str | None = None
    attrs: dict[str, str] = field(default_factory=dict)


@dataclass
class Graph:
    """Parsed in-memory graph."""

    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    link_labels: list[str] = field(default_factory=list)

    def add_node(self, label: str) -> Node:
        if label not in self.nodes:
            self.nodes[label] = Node(label=label)
        return self.nodes[label]


_LABELLED_EDGE = re.compile(
    r"\s*(?P<style1>[-=.]+)\s+(?P<label>[^<>\s][^<>\n]*?)\s+"
    r"(?P<style2>[-=.]+)(?P<after>>)?"
)


def _tokens(line: str) -> list[tuple[str, str]]:
    """Tokenise one line into (kind, value) pairs: ('node'|'edge', text).

    An edge written ``-- label -->`` yields an ``edge`` token immediately
    followed by a ``label`` token; ``_stitch`` attaches the label to the edge.
    """
    out: list[tuple[str, str]] = []
    pos = 0
    while pos < len(line):
        m = _TOK.match(line, pos)
        if not m:
            pos += 1
            continue
        pos = m.end()
        if m.group(2) is not None or m.group(3) is not None:
            op = m.group(2) or m.group(3)
            le = _LABELLED_EDGE.match(line, m.start())
            if le:
                out.append(("edge", op))
                out.append(("label", le.group("label")))
                pos = le.end()
            else:
                out.append(("edge", op))
        elif m.group(1) is not None:
            out.append(("node", m.group(1)[1:-1].strip()))
        elif m.group(4) is not None:
            out.append(("attr", m.group(4)))
        else:
            out.append(("node", m.group(5)))
    return out


def _edge_style(op: str) -> str | None:
    """Map a connector string to a style name (upstream Parser::_edge_style)."""
    if re.fullmatch(r"=+", op):
        return "double"
    if re.fullmatch(r"\.+", op):
        return "dotted"
    if re.fullmatch(r"~+", op):
        return "wave"
    if re.fullmatch(r"#+", op):
        return "bold"
    if re.fullmatch(r"(\.-)+", op):
        return "dot-dash"
    if re.fullmatch(r"(\.\.-)+", op):
        return "dot-dot-dash"
    return None


def _stitch(g: Graph, tokens: list[tuple[str, str]]) -> None:
    """Turn a token stream (node edge node edge ...) into edges on ``g``."""
    prev: str | None = None
    pending_op: str | None = None
    pending_label: str | None = None
    i = 0
    while i < len(tokens):
        kind, value = tokens[i]
        if kind == "label":
            pending_label = value
            i += 1
            continue
        if kind == "edge":
            pending_op = value
            i += 1
            continue
        if kind == "attr":
            if prev is not None:
                g.nodes[prev].attrs.update(_parse_attrs(value))
            i += 1
            continue
        g.add_node(value)
        if pending_op is not None and prev is not None:
            e = Edge(source=prev, target=value)
            e.directed_to_target = pending_op.endswith(">")
            e.directed_from_source = pending_op.startswith("<")
            e.label = pending_label
            e.style = _edge_style(pending_op.strip("<>"))
            g.edges.append(e)
        pending_op = None
        pending_label = None
        prev = value
        i += 1


def parse_graph(text: str, *, link_as_default_label: bool = False) -> Graph:
    """Parse graph DSL text into a :class:`Graph`."""

    g = Graph()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        _stitch(g, _tokens(line))
    return g
