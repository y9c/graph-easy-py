"""Terminal display-width helpers for box layout.

The renderer lays out nodes and labels on a monospaced terminal grid, where
"width" is measured in *display cells*, not code points. A CJK or emoji
character (``中文``, ``①``, ``🚀``) occupies two cells, so naive ``len()``
misaligns box borders for non-ASCII labels.

This module provides a small, dependency-free width function built on the
Unicode ``East_Asian_Width`` property: wide and fullwidth chars count as 2
cells, zero-width/combining marks as 0, everything else (incl. ambiguous
width) as 1.
"""

from __future__ import annotations

import unicodedata


def display_width(text: str) -> int:
    """Return the number of terminal cells ``text`` occupies."""
    total = 0
    for ch in text:
        w = unicodedata.east_asian_width(ch)
        if w in ("W", "F"):
            total += 2
        elif unicodedata.combining(ch):
            total += 0
        else:
            total += 1
    return total


def truncate_display(text: str, budget: int) -> str:
    """Truncate ``text`` to at most ``budget`` display cells.

    Wide characters are kept whole; the string is cut only at a character
    boundary, so no partial CJK glyph is emitted. If a single wide character
    already exceeds the budget, it is dropped.
    """
    out: list[str] = []
    used = 0
    for ch in text:
        w = display_width(ch)
        if used + w > budget:
            break
        out.append(ch)
        used += w
    return "".join(out)
