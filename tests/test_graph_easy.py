"""Tests for the Graph::Easy Python port core subset.

Cases are derived from Graph::Easy upstream documentation/examples and from
fundamental box-geometry invariants.
"""

from __future__ import annotations

import pytest

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


def test_render_unicode_merge_junction_points_toward_vertical_edge():
    """A branch entering from below must join with a downward-facing tee."""
    out = render(parse_graph("[ A ] --> [ C ]\n[ B ] --> [ C ]"))
    lines = out.splitlines()
    junctions = [
        (x, y, ch) for y, line in enumerate(lines) for x, ch in enumerate(line) if ch in "┬┴"
    ]
    assert len(junctions) == 1
    x, y, ch = junctions[0]
    assert lines[y + 1][x] == "│"
    assert ch == "┬"


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


def test_empty_group_name_is_ignored():
    # a stray "( )" (no group name) must not create a frame labelled ")"
    g = parse_graph("( ) [ A ]")
    assert "A" in g.nodes
    assert not g.nodes["A"].attrs.get("group")
    out = render(g)
    assert "┌───┐" in out
    assert "┌ )" not in out


def test_group_name_with_trailing_close_paren_is_cleaned():
    # "( name )" leaves a trailing ')' before the node; it must not leak
    # into the group label.
    out = render(parse_graph("( Pipeline ) [ A ] --> [ B ]"))
    assert "Pipeline" in out
    assert "Pipeline)" not in out


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


# ---- layout: fan-out / parallel branches ------------------------------------


def test_fan_out_keeps_all_edges():
    g = parse_graph("[ S ] --> [ A ]\n[ S ] --> [ B ]\n[ S ] --> [ C ]\n")
    assert len(g.edges) == 3
    out = render(g)
    # all three targets appear
    assert "A" in out and "B" in out and "C" in out


def test_diamond_renders_all_four_edges():
    g = parse_graph("[ A ] --> [ B ]\n[ A ] --> [ C ]\n[ B ] --> [ D ]\n[ C ] --> [ D ]\n")
    assert len(g.edges) == 4
    out = render(g)
    assert "D" in out and "B" in out and "C" in out


def test_parallel_paths_merge_cleanly():
    g = parse_graph("[ S ] --> [ P1 ]\n[ S ] --> [ P2 ]\n[ P1 ] --> [ T ]\n[ P2 ] --> [ T ]\n")
    out = render(g)
    assert "P1" in out and "P2" in out and "T" in out


def test_edge_corners_use_box_chars():
    # a downward branch: the source arm turns down (┐) and the vertical
    # arm turns right into the target (└)
    out = render(parse_graph("[ A ] --> [ B ]\n[ A ] --> [ C ]"))
    assert "┐" in out and "└" in out
    # an upward merge: B's vertical arm joins the A->D through-line from
    # below, so the junction is a downward tee (┬), not a broken edge
    out2 = render(parse_graph("[ A ] --> [ D ]\n[ B ] --> [ D ]"))
    assert "┘" in out2 and "┬" in out2
    # ASCII corners fall back to "+"
    out3 = render(parse_graph("[ A ] --> [ B ]\n[ A ] --> [ C ]"), ascii_style=True)
    assert "\u250c" not in out3 and "+" in out3


def test_filled_arrowhead():
    g = parse_graph("[ A ] -- { arrowshape: filled; } --> [ B ]")
    assert g.edges[0].attrs.get("arrowshape") == "filled"
    out = render(g)
    assert "▶" in out


def test_default_arrowhead_is_filled_triangle():
    # unicode output uses ▶/◀ by default; arrowshape: plain opts out
    out = render(parse_graph("[ A ] --> [ B ]"))
    assert "▶" in out and ">" not in out
    out2 = render(parse_graph("[ A ] -- { arrowshape: plain; } --> [ B ]"))
    assert ">" in out2 and "▶" not in out2


def test_color_attrs_when_enabled():
    g = parse_graph("[ A ] { fill: red; color: white; } --> [ B ]")
    out = render(g, color=True)
    assert "\x1b[41" in out  # red background
    assert ";37" in out  # white foreground


def test_color_attrs_disabled_by_default():
    g = parse_graph("[ A ] { fill: red; } --> [ B ]")
    assert "\x1b[" not in render(g)


def test_hex_truecolor_foreground_and_background():
    g = parse_graph("[ A ] { color: #ff0000; fill: #0000ff; } --> [ B ]")
    out = render(g, color=True)
    assert "38;2;255;0;0" in out  # red text via true-colour
    assert "48;2;0;0;255" in out  # blue background via true-colour


def test_hex_shorthand_triplet():
    # #RGB shorthand expands to #RRGGBB
    assert "38;2;170;187;204" in render(parse_graph("[ A ] { color: #abc; } --> [ B ]"), color=True)


def test_extended_named_colours():
    out = render(parse_graph("[ A ] { color: deeppink; fill: lavender; } --> [ B ]"), color=True)
    assert "38;2;255;20;147" in out  # deeppink
    assert "48;2;230;230;250" in out  # lavender


def test_colourbrewer_scheme_index():
    # color: <n>; scheme: <name> resolves against the palette
    out = render(parse_graph("[ A ] { color: 3; scheme: blues5; } --> [ B ]"), color=True)
    assert "38;2;107;174;214" in out  # blues5[3]
    out2 = render(parse_graph("[ A ] { fill: 2; scheme: set1; } --> [ B ]"), color=True)
    assert "48;2;55;126;184" in out2  # set1[2]


def test_border_color_truecolour():
    out = render(parse_graph("[ A ] { border-color: #00ff00; } --> [ B ]"), color=True)
    assert "38;2;0;255;0" in out


def test_unknown_colour_survives_render():
    # an unrecognised colour must not crash; it just renders uncoloured
    out = render(parse_graph("[ A ] { color: notacolour; } --> [ B ]"), color=True)
    assert "notacolour" not in out
    assert "│ A │" in out


# ---- routing regressions ----------------------------------------------------


@pytest.mark.parametrize("ascii_style", [False, True])
@pytest.mark.parametrize(
    ("text", "source", "arrow_count"),
    [
        ("[ A ] --> [ C ]\n[ B ] --> [ C ]", "B", 1),
        ("[ A ] --> [ B ]\n[ A ] --> [ C ]", "A", 2),
        ("[ A ] --> [ B ] --> [ D ]\n[ A ] --> [ C ] --> [ D ]", "C", 3),
    ],
)
def test_adjacent_bent_edges_leave_source_center(text, source, arrow_count, ascii_style):
    """Bent branches and merges leave the source center without extending its bottom border."""
    out = render(parse_graph(text), ascii_style=ascii_style)
    lines = out.splitlines()
    border = "|" if ascii_style else "│"
    label = f"{border} {source} {border}"
    y = next(i for i, line in enumerate(lines) if label in line)
    x = lines[y].index(label) + len(label)
    horizontal = "-" if ascii_style else "─"
    assert lines[y][x] == horizontal
    assert len(lines[y + 1]) <= x or lines[y + 1][x] == " "
    assert out.count(">" if ascii_style else "▶") == arrow_count


@pytest.mark.parametrize("ascii_style", [False, True])
def test_branch_junction_stays_connected(ascii_style):
    """A minimal two-edge branch keeps its shared junction connected."""
    lines = render(
        parse_graph("[ A ] --> [ B ]\n[ A ] --> [ C ]"), ascii_style=ascii_style
    ).splitlines()
    vertical = "|" if ascii_style else "│"
    source = f"{vertical} A {vertical}"
    y = next(i for i, line in enumerate(lines) if source in line)
    source_end = lines[y].index(source) + len(source)
    junction_x = next(
        x for x in range(source_end, len(lines[y + 2])) if lines[y + 2][x] == vertical
    )
    # T-junction orientation is covered by the separate Unicode mapping fix.
    junctions = {"+"} if ascii_style else {"┬", "┴"}
    assert lines[y][junction_x] in junctions


def test_span_edge_does_not_clobber_box():
    # A->B skips the layer that holds C; the intermediate box must stay intact
    out = render(parse_graph("[ A ] --> [ C ]\n[ A ] --> [ B ]\n[ C ] --> [ B ]"))
    assert "│ A │" in out and "│ C │" in out and "│ B │" in out
    # both edges entering B share its left port (one merged arrowhead);
    # the spanning edge takes a detour row below the diagram
    assert out.count("▶") == 2
    assert "└─" in out and out.splitlines()[-1].rstrip().endswith("┘")


def test_cycle_back_edge_renders():
    out = render(parse_graph("[ A ] --> [ B ]\n[ B ] --> [ C ]\n[ C ] --> [ A ]"))
    assert out.count("┌───┐") == 3
    # every box intact, back edge routed through a detour row below
    assert "│ A │" in out and "│ B │" in out and "│ C │" in out
    assert "┬" in out
    assert "└─" in out  # detour row corner


def test_selfloop_renders():
    out = render(parse_graph("[ A ] --> [ A ]"))
    assert "▲" in out  # re-entry arrowhead into the box bottom
    assert "┐" in out and "┘" in out  # loop corners


def test_bidirectional_shows_both_arrows():
    out = render(parse_graph("[ A ] <--> [ B ]"))
    assert "◀" in out and "▶" in out


def test_double_style_edge():
    out = render(parse_graph("[ A ] ==> [ B ]"))
    assert "═" in out


def test_attr_label_is_used():
    # a { label: x; } block on the edge sets the edge label
    g = parse_graph("[ A ] -- { label: ret; } --> [ B ]")
    assert g.edges[0].label == "ret"
    out = render(g)
    assert "ret" in out


# ---- CLI ---------------------------------------------------------------------


def test_cli_main(tmp_path, capsys):
    from graph_easy.cli import main

    p = tmp_path / "g.txt"
    p.write_text("[ A ] --> [ B ]\n", encoding="utf-8")
    assert main([str(p), "--ascii", "--no-color"]) == 0
    out = capsys.readouterr().out
    assert "A" in out and "B" in out and "-->" in out


def test_cli_missing_file(capsys):
    from graph_easy.cli import main

    assert main(["/nonexistent/graph-easy-test-file.txt"]) == 1
    assert "graph-easy:" in capsys.readouterr().err


def test_bent_edge_does_not_clobber_unrelated_node_border():
    # issue #5: B -> C must not run its vertical along Longest's right
    # border. Longest is a leaf; its box border must stay intact (no fused
    # ┤ that would imply a false Longest -> C edge).
    out = render(parse_graph("[ R ] -> [ Longest ]\n[ R ] -> [ B ]\n[ B ] -> [ C ]"))
    assert "│ Longest │" in out
    assert "▶" in out  # R -> Longest arrow still present
    assert "┤" not in out  # Longest's right border not fused to B->C


def test_wide_sibling_bent_edge_keeps_all_boxes_intact():
    # A wide leaf sibling must never have its border clobbered by a bent
    # edge routed through a channel centre; every box in the diagram stays
    # whole (no cell turned into a ┤/┐/└ that eats into a frame).
    out = render(
        parse_graph(
            "[ R ] -> [ BiggestNode ]\n[ R ] -> [ B ]\n[ B ] -> [ C ]\n"
            "[ B ] -> [ D ]\n[ C ] -> [ E ]\n[ D ] -> [ E ]"
        )
    )
    for label in ("BiggestNode", "B", "C", "D", "E"):
        assert f"│ {label} │" in out or f"│ {label} " in out
    # R -> BiggestNode arrow survives
    assert "▶" in out


def test_ascii_bent_edge_center_exit():
    # ASCII mirror of the adjacent bent edge: the source must still exit at
    # its centre row (PR4) and not clobber a sibling (PR5).
    out = render(
        parse_graph("[ R ] -> [ Longest ]\n[ R ] -> [ B ]\n[ B ] -> [ C ]"), ascii_style=True
    )
    assert "| Longest |" in out
    assert "+" in out


def _display_width(s: str) -> int:
    """Terminal cells a string occupies (CJK wide chars = 2)."""
    import unicodedata

    total = 0
    for ch in s:
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


@pytest.mark.parametrize(
    "text",
    [
        "[ 中文 ] -> [ B ]",
        "[ 北京 ] -> [ 上海 ] -> [ 广州 ]",
        "[ A ] -> [ 北京 ]\n[ A ] -> [ 东京 ]\n[ 北京 ] -> [ C ]\n[ 东京 ] -> [ C ]",
        "[ 中文 ] -> [ 东京 ]",
        # Japanese hiragana / katakana / kanji and mixed CJK+Latin labels all
        # render at their true display width so box borders stay aligned.
        "[ とうきょう ] -> [ おおさか ] -> [ きょうと ]",
        "[ 東京 ] -> [ 大阪 ] -> [ 京都 ]",
        "[ 中国 ] -> [ Tokyo ] -> [ 大阪 ]",
        "[ ｶﾀｶﾅ ] -> [ ひらがな ]",
    ],
)
def test_wide_char_boxes_align_by_display_width(text):
    # CJK/emoji labels consume two display cells each; the box border rows
    # must match the interior rows in *display* width (not code points) so
    # the frame stays rectangular in a monospaced terminal. A top border and
    # its matching bottom border must have equal display width.
    out = render(parse_graph(text))
    lines = out.splitlines()
    for i, line in enumerate(lines[:-2]):
        if line.lstrip().startswith("\u250c") and lines[i + 2].lstrip().startswith("\u2514"):
            assert _display_width(line) == _display_width(lines[i + 2])


def test_wide_char_kernel_widths():
    # node geometry: inner_width / width must count display cells, not chars
    from graph_easy.node import Node

    assert Node(label="中文").inner_width() == 4  # 中+文 each two cells
    assert Node(label="中文").width() == 2 + 2 * 1 + 4
    assert Node(label="abc").inner_width() == 3
    assert Node(label="とうきょう").inner_width() == 10  # 5 hiragana * 2 cells
    assert Node(label="東京").inner_width() == 4


# ---- border-opaque regression (wire must not punch through a box frame) ----


def _box_border_junctions(text):
    """Return (node, x, y, glyph) if a junction glyph sits on a box border."""
    import importlib

    from graph_easy._width import display_width

    R = importlib.import_module("graph_easy.render")
    g = parse_graph(text)
    out = render(g)
    lines = out.splitlines()
    comp = R._components(g)[0]
    layers = R._barycenter_order(R._layers(comp, g), g)
    layer_boxes = [[R._box(g.nodes[node], R._BOX_UNICODE) for node in layer] for layer in layers]
    col_w = [max(max(display_width(row) for row in b) for b in bxs) for bxs in layer_boxes]
    colx = []
    x = 0
    for w in col_w:
        colx.append(x)
        x += w + R._CHANNEL
    y_offs = []
    for c, bxs in enumerate(layer_boxes):
        offs = []
        y = 0
        for b, _node in zip(bxs, layers[c], strict=True):
            offs.append(y)
            y += len(b) + 1
        y_offs.append(offs)
    for c, bxs in enumerate(layer_boxes):
        for i, b in enumerate(bxs):
            x0, y0 = colx[c], y_offs[c][i]
            w = display_width(b[0])
            h = len(b)
            for yy in (y0, y0 + h - 1):
                for xx in range(x0, x0 + w):
                    if yy < len(lines) and xx < len(lines[yy]):
                        ch = lines[yy][xx]
                        if ch in "\u253c\u252c\u2534\u2524\u251c":
                            return (layers[c][i], xx, yy, ch)
    return None


@pytest.mark.parametrize(
    "text",
    [
        "[ C ] --> [ B ]\n[ B ] --> [ D ]\n[ B ] --> [ C ]",
        "[ B ] --> [ Longest ]\n[ C ] --> [ B ]\n[ B ] --> [ X ]\n[ B ] --> [ C ]",
        "[ A ] --> [ B ]\n[ B ] --> [ C ]\n[ C ] --> [ D ]\n[ D ] --> [ B ]",
        "[ X ] --> [ B ]\n[ D ] --> [ X ]\n[ B ] --> [ D ]\n[ C ] --> [ X ]",
    ],
)
def test_wire_never_punches_through_box_border(text):
    # A wire routed past an unrelated node must not merge with its frame
    # (which would turn a box border into a junction glyph and fabricate a
    # false edge).
    assert _box_border_junctions(text) is None


def test_forward_detour_exits_source_centre():
    # A span edge degraded to a detour must leave the source from its centre
    # row, not its bottom border (otherwise a multi-out-edge node draws a
    # branch from its corner).
    out = render(parse_graph("[ B ] --> [ C ]\n[ B ] --> [ X ]\n[ C ] --> [ X ]\n[D] --> [B]"))
    lines = out.splitlines()
    by = next(i for i, line in enumerate(lines) if "\u2502 B \u2502" in line)
    bx = lines[by].index("\u2502 B \u2502") + len("\u2502 B \u2502")
    assert lines[by][bx] == "\u2500"
    # the box bottom border is not extended with a rightward wire
    assert "\u2514\u2500\u2500\u2500\u2518\u2500\u2500" not in lines[by + 1]
