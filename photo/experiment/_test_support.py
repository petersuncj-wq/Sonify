"""Shared test helpers for the engine layer.

`_overlap_peak()` used to live in `studio_grammar.py`, i.e. a test-only
assertion helper shipped inside a production module.  It now lives here so
that the production modules stay free of test scaffolding, while the
public `studio_grammar.overlap_peak()` entry point keeps older call sites
working.
"""
from __future__ import annotations


def overlap_peak(notes) -> int:
    """Maximum number of simultaneously sounding notes.

    Times are rounded to microseconds so that a note's end ties with
    another note's start and is processed as an "off" before the next
    "on" (avoids float drift).
    """
    events = []
    for n in notes:
        events.append((round(float(n['start']), 6), 1))
        events.append((round(float(n['start']) + float(n['duration']), 6), -1))
    events.sort()
    cur = peak = 0
    for _, v in events:
        cur += v
        peak = max(peak, cur)
    return peak


__all__ = ['overlap_peak']
