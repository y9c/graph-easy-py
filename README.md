# graph-easy

A **Python port** of [Graph::Easy](https://github.com/ironcamel/Graph-Easy),
the Perl tool that lays out directed/undirected graphs and renders them as
**ASCII art** (box-and-wire diagrams rendered in the terminal).

This project faithfully translates the original Perl implementation to Python,
in order to provide the same functionality to Python users / as a native Python
library and command-line tool.

## Provenance & License

- Original: **Graph::Easy**, Copyright (C) 2004 - 2008 by **Tels**
  (<http://bloodgate.com/>).
- Upstream repository: <https://github.com/ironcamel/Graph-Easy>
- This port is licensed under the **GNU General Public License, version 2 or
  (at your option) any later version** — the same license as the original
  Graph::Easy, because a port is a derivative work.

See [`LICENSE`](./LICENSE) for the full LGPL/ GPL text.

### Third-party color schemes

This product includes color specifications and designs developed by Cynthia
Brewer (<http://colorbrewer.org/>), used under the
Apache-Style Software License for ColorBrewer Color Schemes v1.1,
© 2002 Cynthia Brewer, Mark Harrower, and The Pennsylvania State University.
See the header of the original `Graph::Easy::Attributes` for the full notice.

## Status

Actively-developed port. Currently implemented:

- **DSL parser**: `[ label ]`/bare nodes, `-->` `<--` `<-->` `--` arrows,
  labelled edges (`-- label -->`), multiline labels (`\n`), comments
- **Layout engine**: longest-path layering with orthogonal edge routing —
  chains, branches, merges and cycles all render correctly; independent
  components stack as separate diagrams
- **Edge line styles** (faithful to upstream `Parser::_edge_style`):
  `--` solid, `..` dotted, `==` double, `~~` wave, `##` bold, `.-`/`..-` dot-dash
- **Two output charsets**: Unicode box-drawing by default
  (`┌──┐ ──> ══ ║ ·`), plain ASCII via `--ascii`

The heavier automatic layout engine (`Graph::Easy::Layout` grid solver) is a
follow-up milestone.

## Usage

```console
$ printf '[ Bonn ] --> [ Berlin ] --> [ Hamburg ]\n' | graph-easy
┌──────┐         ┌────────┐         ┌─────────┐
│ Bonn │ ───────>│ Berlin │ ───────>│ Hamburg │
└──────┘         └────────┘         └─────────┘

# plain-ASCII output
$ printf '[ A ] ..> [ B ]\n' | graph-easy --ascii
+---+         +---+
| A | .......>| B |
+---+         +---+
```

## Development

```console
$ python -m venv .venv && source .venv/bin/activate
$ pip install -e '.[dev]'
$ pytest
```

## Acknowledgments

Thanks to Tels and the Graph::Easy contributors whose careful layout and
rendering work this port builds upon.
