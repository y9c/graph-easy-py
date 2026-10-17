"""Command-line entry point — read graph DSL on stdin, print ASCII art."""

from __future__ import annotations

import argparse
import sys

from graph_easy import __version__
from graph_easy.export import graphviz_available, render_dot, to_dot
from graph_easy.parser import parse_graph
from graph_easy.render import render


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="graph-easy",
        description="Layout and render a graph as ASCII art (Python port of Graph::Easy).",
    )
    ap.add_argument(
        "file",
        nargs="?",
        help="read DSL from FILE instead of stdin ('-' = stdin)",
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    ap.add_argument(
        "--ascii",
        action="store_true",
        help="use plain ASCII box/line characters (default: Unicode)",
    )
    ap.add_argument(
        "--autolabel",
        action="store_true",
        help="label every unlabelled edge (e.g. 'A -> B')",
    )
    ap.add_argument(
        "--color",
        nargs="?",
        const="on",
        choices=["on", "off", "auto"],
        help="apply ANSI colours (default: auto, i.e. only on a TTY)",
    )
    ap.add_argument(
        "--no-color",
        dest="color",
        action="store_const",
        const="off",
        help="disable ANSI colours",
    )
    ap.add_argument(
        "--dot",
        action="store_const",
        const="dot",
        dest="format",
        help="output Graphviz DOT instead of ASCII art",
    )
    ap.add_argument(
        "--format",
        choices=["dot", "svg", "png"],
        help="output format (dot/svg/png; svg/png require the 'dot' binary)",
    )
    ap.add_argument(
        "--engine",
        default="dot",
        help="graphviz layout engine for svg/png output (default: dot)",
    )
    ap.set_defaults(color="auto", format=None)
    args = ap.parse_args(argv)

    if args.file and args.file != "-":
        try:
            with open(args.file, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            print(f"graph-easy: {exc}", file=sys.stderr)
            return 1
    else:
        text = sys.stdin.read()

    graph = parse_graph(text)
    fmt = args.format
    if fmt:
        if fmt == "dot":
            sys.stdout.write(to_dot(graph))
            return 0
        result = render_dot(graph, fmt, engine=args.engine)
        if result is None:
            if not graphviz_available():
                print(
                    f"graph-easy: the 'dot' binary is required for '{fmt}' output ",
                    file=sys.stderr,
                )
            else:
                print(f"graph-easy: could not render '{fmt}'", file=sys.stderr)
            return 1
        sys.stdout.buffer.write(result)
        return 0

    if args.color == "auto":
        args.color = sys.stdout.isatty()
    elif args.color == "on":
        args.color = True
    else:
        args.color = False
    output = render(graph, ascii_style=args.ascii, color=args.color, autolabel=args.autolabel)
    sys.stdout.write(output + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
