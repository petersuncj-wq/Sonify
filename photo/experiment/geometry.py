"""Pure geometry helpers shared by every producer.

This module is the single implementation of the line-art -> path graph
pipeline.  It exists so that no other module has to import a *script*
(`run.py`) just to reach `trace()` / `extract()`; that pattern used to
drag the whole script (and its import-time side effects) into every
import, and made `lab.cv2` style attribute forwarding possible.

Everything here is deterministic and free of import-time side effects.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

# 8-neighbourhood offsets used to walk the skeleton graph.
NEIGHBOUR_OFFSETS = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1))


def _skeleton_adjacency(mask: np.ndarray):
    """Return (adjacency, width) for a boolean skeleton mask.

    `adjacency` maps a pixel id (`y * width + x`) to the sorted list of
    neighbouring pixel ids.  The 8-neighbourhood is computed with NumPy
    shifts instead of per-pixel Python set lookups; the old version did
    up to 8 set probes for every one of ~12 000 pixels.

    A diagonal neighbour is only kept when it is not already reachable
    through the 4-neighbourhood (the classic "no corner cutting" rule).
    """
    mask = np.asarray(mask) > 0
    height, width = mask.shape
    ids = np.full((height, width), -1, dtype=np.int64)
    ys, xs = np.nonzero(mask)
    ids[ys, xs] = ys.astype(np.int64) * width + xs
    sources, targets = [], []
    for dy, dx in NEIGHBOUR_OFFSETS:
        sy0, sy1 = max(0, -dy), min(height, height - dy)
        sx0, sx1 = max(0, -dx), min(width, width - dx)
        src = ids[sy0:sy1, sx0:sx1]
        dst = ids[sy0 + dy:sy1 + dy, sx0 + dx:sx1 + dx]
        ok = (src >= 0) & (dst >= 0)
        if dx and dy:
            horizontal = ids[sy0:sy1, sx0 + dx:sx1 + dx]
            vertical = ids[sy0 + dy:sy1 + dy, sx0:sx1]
            ok &= ~((horizontal >= 0) | (vertical >= 0))
        sources.append(src[ok])
        targets.append(dst[ok])
    src = np.concatenate(sources) if sources else np.empty(0, dtype=np.int64)
    dst = np.concatenate(targets) if targets else np.empty(0, dtype=np.int64)
    adjacency: dict[int, list[int]] = {}
    if len(src):
        order = np.argsort(src, kind='stable')
        src, dst = src[order], dst[order]
        edges = np.flatnonzero(np.diff(src)) + 1
        starts = np.concatenate(([0], edges))
        ends = np.concatenate((edges, [len(src)]))
        for a, b in zip(starts, ends):
            adjacency[int(src[a])] = sorted(int(x) for x in dst[a:b])
    return adjacency, width


def trace(skeleton: np.ndarray):
    """Return the ordered pixel paths that make up a thinned skeleton."""
    adjacency, width = _skeleton_adjacency(skeleton)
    visited: set[int] = set()
    paths: list[list[tuple[int, int]]] = []

    def edge_key(a: int, b: int) -> int:
        # One integer key instead of a sorted tuple: no tuple allocation per
        # graph step, and hashing an int is markedly cheaper than hashing a
        # tuple of two ints.
        return a * width + b if a < b else b * width + a

    def walk(start: int, second: int) -> list[int]:
        path = [start]
        previous, current = start, second
        while True:
            visited.add(edge_key(previous, current))
            path.append(current)
            neighbours = adjacency.get(current, [])
            if len(neighbours) != 2 or current == start:
                break
            nxt = neighbours[0] if neighbours[1] == previous else neighbours[1]
            if edge_key(current, nxt) in visited:
                break
            previous, current = current, nxt
        return path

    # Endpoints first (degree != 2) so open strokes are walked from their tip.
    for pixel in sorted(adjacency, key=lambda p: (len(adjacency[p]) == 2, p)):
        for neighbour in adjacency[pixel]:
            if edge_key(pixel, neighbour) not in visited:
                paths.append(walk(pixel, neighbour))
    return [[(node // width, node % width) for node in path] for path in paths]


def extract(gray: np.ndarray):
    """Extract line-art paths from a grayscale image.

    Returns (mask, skeleton, paths, repeat_groups, metrics).
    """
    # Thin strokes, never redraw model-generated geometry.
    mask = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY_INV, 25, 12)
    mask[:8] = 0
    mask[-8:] = 0
    mask[:, :8] = 0
    mask[:, -8:] = 0
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    keep = np.zeros(count, dtype=np.uint8)
    keep[1:] = (stats[1:, cv2.CC_STAT_AREA] >= 12) * 255
    mask = keep[labels]
    skeleton = cv2.ximgproc.thinning(mask)
    raw = trace(skeleton)
    height, width = gray.shape
    candidates = []
    for path in raw:
        a = np.array([(x, y) for y, x in path], dtype=np.float32)
        length = float(np.linalg.norm(np.diff(a, axis=0), axis=1).sum())
        if length < max(width, height) * .025:
            continue
        simplified = cv2.approxPolyDP(a.reshape(-1, 1, 2), 1.4, False).reshape(-1, 2)
        if len(simplified) < 2:
            continue
        chord = float(np.linalg.norm(a[-1] - a[0]))
        straight = chord / max(length, 1)
        dx, dy = a[-1] - a[0]
        angle = math.degrees(math.atan2(float(dy), float(dx))) % 180
        kind = ('horizontal' if straight > .9 and min(angle, 180 - angle) < 12
                else 'vertical' if straight > .9 and abs(angle - 90) < 12
                else 'curve')
        candidates.append(dict(
            points=(simplified / [width, height]).round(5).tolist(),
            length=round(length, 2), kind=kind, angle=round(angle, 1),
            closed=bool(chord < 3),
            bbox=[float(a[:, 0].min() / width), float(a[:, 1].min() / height),
                  float(a[:, 0].max() / width), float(a[:, 1].max() / height)],
            score=length * (1.15 if kind == 'curve' else 1)))
    # Repetition candidates: nearby, similarly long, similarly directed vertical strokes.
    vertical = [p for p in candidates if p['kind'] == 'vertical']
    groups: list[list[dict]] = []
    used: set[int] = set()
    for i, p in enumerate(vertical):
        if i in used:
            continue
        cx = (p['bbox'][0] + p['bbox'][2]) / 2
        cy = (p['bbox'][1] + p['bbox'][3]) / 2
        group = []
        for j, q in enumerate(vertical):
            if j in used:
                continue
            qx = (q['bbox'][0] + q['bbox'][2]) / 2
            qy = (q['bbox'][1] + q['bbox'][3]) / 2
            if abs(qy - cy) < .045 and abs(qx - cx) < .25 and .65 < p['length'] / q['length'] < 1.55:
                group.append(j)
        if len(group) >= 3:
            used.update(group)
            groups.append([vertical[j] for j in group])
    ranked = sorted(candidates, key=lambda p: -p['score'])
    selected = ranked[:36]
    for group in groups[:3]:
        for p in group:
            if p not in selected:
                selected.append(p)
    selected = selected[:60]
    for i, p in enumerate(selected):
        p['id'] = f'p{i:03d}'
    repeat = []
    for group in groups:
        ids = [p['id'] for p in group if 'id' in p]
        if len(ids) >= 3:
            repeat.append(ids)
    return mask, skeleton, selected, repeat, dict(
        raw_paths=len(raw), eligible_paths=len(candidates), selected_paths=len(selected))
