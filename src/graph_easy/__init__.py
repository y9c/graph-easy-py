"""graph-easy-py — a Python port of Graph::Easy (GPL-2.0-or-later).

Port of Graph::Easy (c) Tels, 2004-2008, <http://bloodgate.com/>.
"""

from graph_easy.parser import Edge, Graph, parse_graph
from graph_easy.render import render

__version__ = "0.0.1"
__all__ = ["Edge", "Graph", "parse_graph", "render", "__version__"]
