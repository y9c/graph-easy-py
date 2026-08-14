"""Command-line entry point — read graph DSL on stdin, print ASCII art."""

from __future__ import annotations

import argparse
import sys

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
    ap.add_argument(
        "--ascii",
        action="store_true",
        help="use plain ASCII box/line characters (default: Unicode)",
    )
    ap.add_argument(
        "--color",
        action="store_true",
        help="apply ANSI colours from fill/color attributes",
    )
    ap.add_argument(
        "--no-color",
        dest="color",
        action="store_false",
        help="disable ANSI colours (default when output is piped)",
    )
    ap.set_defaults(color=None)
    args = ap.parse_args(argv)

    if args.file and args.file != "-":
        with open(args.file, encoding="utf-8") as fh:
            text = fh.read()
    else:
        text = sys.stdin.read()

    if args.color is None:
        args.color = sys.stdout.isatty()
    graph = parse_graph(text)
    output = render(graph, ascii_style=args.ascii, color=args.color)
    sys.stdout.write(output + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
