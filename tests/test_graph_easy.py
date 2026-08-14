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


# ---- shapes & attributes ----------------------------------------------------

def test_node_attribute_block_applies_shape():
    g = parse_graph("[ Start ] { shape: diamond; } --> [ A ]")
    assert g.nodes["Start"].attrs.get("shape") == "diamond"
    out = render(g)
    assert "/" in out and "\\" in out


def test_unknown_attribute_falls_back_to_normal_box():
    out = render(parse_graph("[ A ] { foo: bar; } --> [ B ]"), ascii_style=True)
    assert "+" in out and "A" in out


def test_double_and_rounded_borders():
    out = render(parse_graph("[ A ] { border: double; } --> [ B ] { shape: rounded; }"))
    assert "═" in out  # double border
    assert "╭" in out  # rounded corner


def test_group_parses_and_frames_nodes():
    g = parse_graph("( Pipeline [ Input ] --> [ Output ] )")
    assert g.nodes["Input"].attrs.get("group") == "Pipeline"
    assert g.nodes["Output"].attrs.get("group") == "Pipeline"
    out = render(g)
    assert "Pipeline" in out  # group label on the frame


def test_group_name_with_spaces():
    g = parse_graph("( Stage 1 - QC [ A ] --> [ B ] )")
    assert g.nodes["A"].attrs.get("group") == "Stage 1 - QC"
    out = render(g)
    assert "Stage 1 - QC" in out


def test_shared_node_belongs_to_multiple_groups():
    g = parse_graph("( G One [ A ] --> [ B ] )\n( G Two [ B ] --> [ C ] )")
    assert "G One" in g.nodes["B"].attrs.get("group", "").split(",")
    assert "G Two" in g.nodes["B"].attrs.get("group", "").split(",")
    out = render(g)
    # overlapping group frames merge into a single labelled frame
    assert "G One" in out and "G Two" in out


def test_disjoint_groups_render_separately():
    out = render(parse_graph("( G1 [ X ] --> [ Y ] )\n( G2 [ P ] --> [ Q ] )"))
    assert out.count("┌ G1") == 1
    assert out.count("┌ G2") == 1


def test_filled_arrowhead():
    g = parse_graph("[ A ] -- { arrowshape: filled; } --> [ B ]")
    assert g.edges[0].attrs.get("arrowshape") == "filled"
    out = render(g)
    assert "▶" in out


def test_color_attrs_when_enabled():
    g = parse_graph("[ A ] { fill: red; color: white; } --> [ B ]")
    out = render(g, color=True)
    assert "\x1b[41" in out  # red background
    assert ";37" in out  # white foreground


def test_color_attrs_disabled_by_default():
    g = parse_graph("[ A ] { fill: red; } --> [ B ]")
    assert "\x1b[" not in render(g)
