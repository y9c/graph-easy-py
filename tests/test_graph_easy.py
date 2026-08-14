"""Tests for the Graph::Easy Python port core subset.

Cases are derived from Graph::Easy upstream documentation/examples and from
fundamental box-geometry invariants.
"""

from __future__ import annotations

from graph_easy.node import Node
from graph_easy.parser import parse_graph
from graph_easy.render import render


# ---- box geometry ----------------------------------------------------------

def test_box_dimensions():
    g = parse_graph("[ abc ]")
    n = g.nodes["abc"]
    # label 3 wide, padding_x=1 => borders(2) + 3 + 2 = 7 wide; height 3 = 2 borders + 1 label row
    assert n.width() == 7
    assert n.height() == 3


def test_multiline_label_uses_widest_line():
    g = parse_graph("[ ab\\ndefg ]")
    label = "ab\\ndefg"
    n = g.nodes[label]
    # inner height 2, widest line 4 -> width = 2 + 4 + 2 = 8; height = 2 + 2 = 4
    assert n.width() == 8
    assert n.height() == 4


def test_padding_is_respected():
    n = Node(label="x", padding_x=2, padding_y=1)
    assert n.width() == 2 + 2 * 2 + 1  # borders(2) + 2*padding_x + inner(1)
    assert n.height() == 2 + 2 * 1 + 1  # borders(2) + 2*padding_y + inner(1)


def test_recompute_cache():
    n = Node(label="a")
    n.recompute()
    assert n._width == n.width()


# ---- parsing ---------------------------------------------------------------

def test_parses_simple_chain():
    g = parse_graph("[ A ] --> [ B ] --> [ C ]")
    assert list(g.nodes) == ["A", "B", "C"]
    assert [(e.source, e.target) for e in g.edges] == [("A", "B"), ("B", "C")]


def test_bare_words_and_arrows():
    g = parse_graph("A -> B <- C")
    assert [(e.source, e.target) for e in g.edges] == [("A", "B"), ("B", "C")]
    assert g.edges[1].directed_from_source  # '<-' backwards edge


def test_bidirectional_edge():
    g = parse_graph("[ A ] <--> [ B ]")
    assert g.edges[0].directed_from_source
    assert g.edges[0].directed_to_target


def test_comments_ignored():
    g = parse_graph("# leading\n[A] --> [B]")
    assert list(g.nodes) == ["A", "B"]


# ---- rendering --------------------------------------------------------------

def test_render_smoke_no_crash():
    out = render(parse_graph("[ hello ] --> [ world ]"), ascii_style=True)
    assert "+" in out
    assert "hello" in out
    assert "world" in out
    assert "-->" in out


def test_render_two_components_stack_on_separate_bands():
    out = render(parse_graph("[ A ] --> [ B ]\n[ C ] --> [ D ]"), ascii_style=True)
    # two horizontally separate chains stacked; both labels present
    assert "A" in out and "B" in out and "C" in out and "D" in out
    assert out.count("-->") >= 2


def test_render_unicode_default():
    out = render(parse_graph("[ A ] --> [ B ]"))
    assert "┌" in out and "┐" in out and "│" in out
    assert "─" in out


def test_undirected_edge_renders_as_double_dash():
    g = parse_graph("[ A ] -- [ B ]")
    assert not g.edges[0].directed_to_target
    assert not g.edges[0].directed_from_source
    out = render(g, ascii_style=True)
    assert "--" in out
    assert "-->" not in out


def test_labelled_edge_parses_as_label_not_node():
    g = parse_graph("[ A ] -- hello --> [ B ]")
    assert list(g.nodes) == ["A", "B"]
    assert g.edges[0].label == "hello"
    out = render(g, ascii_style=True)
    assert "hello" in out


def test_render_empty_graph():
    assert render(parse_graph("")) == ""
