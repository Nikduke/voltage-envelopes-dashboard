"""Selection rules for the visible Case and MM chips."""

from __future__ import annotations


def selection_after_click(
    options: list[str], selected: list[str], clicked: str, exclusive: bool
) -> list[str]:
    if clicked not in options:
        return [value for value in selected if value in options]
    if exclusive:
        return [clicked]
    current = [value for value in selected if value in options]
    if clicked in current:
        return [value for value in current if value != clicked]
    return [*current, clicked]
