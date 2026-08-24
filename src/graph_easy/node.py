"""Graph::Easy node model — a labelled text box drawn in ASCII.

Faithful Python port of ``Graph::Easy::Node`` dimensions/label semantics.
A node knows its multi-line label and computes its own rendered box size;
drawing is delegated to the renderer (``graph_easy.render``).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Node:
    """A rectangular labelled node.

    Mirrors the upstream notion that a node's box encloses a (possibly
    multi-line) label with a one-cell padding border on every side, drawn as
    boxes (`+---+`-style corners with `|` and `-` edges).

    Columns are counted in *display cells*; a label line never shrinks the box
    below its widest line.
    """

    label: str
    attr_label: str | None = None
    padding_x: int = 1
    padding_y: int = 0
    shape: str = "normal"
    attrs: dict[str, str] = field(default_factory=dict)

    def label_lines(self) -> list[str]:
        """Split the label into display lines; `\\n` escapes expand to newlines."""
        src = self.attr_label if self.attr_label is not None else self.label
        return src.replace(r"\n", "\n").split("\n")

    def inner_width(self) -> int:
        """Width of the label area in cells (widest line, >= 1)."""
        lines = self.label_lines()
        if not lines:
            return 1
        return max(len(line) for line in lines) or 1

    def inner_height(self) -> int:
        return max(len(self.label_lines()), 1)

    def width(self) -> int:
        """Total box width = 2 borders + padding_x*2 + inner_width."""
        return 2 + self.padding_x * 2 + self.inner_width()

    def height(self) -> int:
        """Total box height = 2 borders + padding_y*2 + inner_height."""
        return 2 + self.padding_y * 2 + self.inner_height()
