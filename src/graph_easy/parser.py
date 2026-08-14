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
    r"|(<[=.\-]*[=.\-]>?)"   # 2: edge with leading '<'  (e.g. <--, <-->)
    r"|([=.\-]*[=.\-]>?)"    # 3: edge without '<'       (e.g. -->, --, ->)
    r"|([^\s]+)"             # 4: bare word
    r")"
)


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


def _tokens(line: str) -> list[tuple[str, str]]:
    """Tokenise one line into (kind, value) pairs: ('node'|'edge', text)."""
    out: list[tuple[str, str]] = []
    pos = 0
    while pos < len(line):
        m = _TOK.match(line, pos)
        if not m:
            pos += 1
            continue
        pos = m.end()
        if m.group(1) is not None:
            out.append(("node", m.group(1)[1:-1].strip()))
        elif m.group(2) is not None or m.group(3) is not None:
            out.append(("edge", m.group(2) or m.group(3)))
        else:
            out.append(("node", m.group(4)))
    return out


def _stitch(g: Graph, tokens: list[tuple[str, str]]) -> None:
    """Turn a token stream (node edge node edge ...) into edges on ``g``."""
    prev: str | None = None
    pending: str | None = None  # edge operator awaiting its target
    for kind, value in tokens:
        if kind == "node":
            g.add_node(value)
            if pending is not None and prev is not None:
                e = Edge(source=prev, target=value)
                e.directed_to_target = pending.endswith(">")
                e.directed_from_source = pending.startswith("<")
                g.edges.append(e)
            pending = None
            prev = value
        else:
            pending = value


def parse_graph(text: str, *, link_as_default_label: bool = False) -> Graph:
    """Parse graph DSL text into a :class:`Graph`."""

    g = Graph()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        _stitch(g, _tokens(line))
    return g
