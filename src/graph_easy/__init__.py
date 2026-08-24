"""graph-easy — a Python port of Graph::Easy (GPL-2.0-or-later).

Port of Graph::Easy (c) Tels, 2004-2008, <http://bloodgate.com/>.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from graph_easy.parser import Edge, Graph, parse_graph
from graph_easy.render import render

try:
    __version__ = version("graph-easy")
except PackageNotFoundError:  # running from an unpacked source tree
    __version__ = "0.0.0"

__all__ = ["Edge", "Graph", "parse_graph", "render", "__version__"]
