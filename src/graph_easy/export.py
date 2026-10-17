"""Export a parsed graph to Graphviz DOT / SVG.

The ASCII/Unicode renderer draws diagrams for a terminal. This module
produces the machine-readable ``DOT`` language (and, when the ``dot`` binary
is available, rendered ``SVG``/``PNG``) so a graph can be visualised with
graphviz or consumed by other tools.
"""

from __future__ import annotations

import shutil
import subprocess

from graph_easy.node import Node
from graph_easy.parser import Edge, Graph

# DOT node shapes that map 1:1 from Graph::Easy shape names.
_DOT_SHAPE: dict[str, str] = {
    "normal": "box",
    "box": "box",
    "rounded": "box",
    "ellipse": "ellipse",
    "circle": "circle",
    "oval": "ellipse",
    "diamond": "diamond",
    "hexagon": "hexagon",
}

# DOT line styles used for edge ``style``.
_DOT_STYLE: dict[str, str] = {
    "solid": "solid",
    "double": "bold",
    "dotted": "dotted",
    "dashed": "dashed",
    "wave": "dashed",
    "bold": "bold",
    "dot-dash": "dashed",
    "dot-dot-dash": "dashed",
}


def _q(s: str) -> str:
    """Quote a DOT string safely."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _node_attrs(node: Node) -> list[str]:
    """Map a node's Graph::Easy attributes to DOT attributes."""
    attrs: list[str] = []
    shape = node.attrs.get("shape", "normal")
    dot_shape = _DOT_SHAPE.get(shape, "box")
    if shape == "rounded":
        attrs.append("style=rounded")
    attrs.append(f"shape={dot_shape}")
    if node.attrs.get("color"):
        attrs.append(f"fontcolor={node.attrs['color']}")
    if node.attrs.get("fill"):
        attrs.append(f"fillcolor={node.attrs['fill']}")
        attrs.append("style=filled")
    if node.attrs.get("border-color", node.attrs.get("bordercolor")):
        attrs.append(f"color={node.attrs.get('border-color', node.attrs.get('bordercolor'))}")
    return attrs


def _edge_attrs(e: Edge) -> list[str]:
    attrs: list[str] = []
    style = e.style or "solid"
    attrs.append(f"style={_DOT_STYLE.get(style, style)}")
    arrow = e.attrs.get("arrow-style", e.attrs.get("arrowshape", "filled"))
    if arrow in ("plain", "open", "line"):
        attrs.append("arrowhead=open")
    if e.label:
        attrs.append(f"label={_q(e.label)}")
    return attrs


def to_dot(graph: Graph) -> str:
    """Return the graph as a ``dot`` (Graphviz) string."""
    if not graph.nodes:
        return "digraph G {\n}\n"
    lines = ["digraph G {"]
    # nodes first (in insertion order), with their attributes
    for name, node in graph.nodes.items():
        attrs = _node_attrs(node)
        if attrs:
            lines.append(f"    {_q(name)} [{', '.join(attrs)}];")
        else:
            lines.append(f"    {_q(name)};")
    # edges
    for e in graph.edges:
        attrs = _edge_attrs(e)
        if attrs:
            lines.append(f"    {_q(e.source)} -> {_q(e.target)} [{', '.join(attrs)}];")
        else:
            lines.append(f"    {_q(e.source)} -> {_q(e.target)};")
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_dot(
    graph: Graph,
    fmt: str = "svg",
    *,
    engine: str = "dot",
) -> bytes | None:
    """Render the graph with the ``dot`` binary, returning the output bytes.

    Returns ``None`` if ``dot`` is not installed or fails.
    """
    dot_bin = shutil.which("dot")
    if dot_bin is None:
        return None
    dot_text = to_dot(graph)
    try:
        proc = subprocess.run(
            [dot_bin, f"-T{fmt}", f"-K{engine}"],
            input=dot_text,
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def graphviz_available() -> bool:
    """Return True if a ``dot`` binary is on PATH."""
    return shutil.which("dot") is not None
