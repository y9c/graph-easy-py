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
    args = ap.parse_args(argv)

    if args.file and args.file != "-":
        with open(args.file, encoding="utf-8") as fh:
            text = fh.read()
    else:
        text = sys.stdin.read()

    graph = parse_graph(text)
    output = render(graph)
    sys.stdout.write(output + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
