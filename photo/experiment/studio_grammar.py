"""Traceable studio grammar v0.5 — high-coverage, hierarchical.

Runs the Sonic Grammar mapping table (docs/PRODUCT_OVERVIEW.md §7) over the
FULL extracted geometry (thousands of skeleton fragments), not a handful of
representative paths, and organises it in two layers:

  Geometry type -> instrument / track
      curve (subject)      -> V0 melody        (长笛 / flute)
      vertical line        -> V1 column        (音乐盒 / music box)
      horizontal line      -> V2 support       (大提琴 / cello)
      closed loop          -> V3 loop          (氛围 Pad / warm pad)
      background (texture) -> V4 accompaniment (弦乐 / string ensemble)

  Spatial layer -> melody vs accompaniment
      subject  (central, large strokes: the pavilion)  -> foreground voices
      background (edges, small strokes: the trees)     -> V4 accompaniment

Mapping rules kept verbatim from the earlier Sonic Grammar:
    vertical position   -> pitch          (1 - y) quantised to the pentatonic SCALE
    horizontal position -> time           (left-to-right scan)
    length              -> note duration
    curvature           -> melodic motion (multi-point arc-length sampling)
    closed contour      -> cyclic accent
    spatial layer       -> voice budget   (<= MAX_CONCURRENT at any instant)

Every emitted event keeps source / source_point / rule / calculation so the
UI can trace note -> geometry, exactly as before.
"""
from __future__ import annotations
import hashlib
import math

import numpy as np

# C D E G A pentatonic across three octaves (same material as v0.1-v0.4).
SCALE = [48, 50, 52, 55, 57, 60, 62, 64, 67, 69, 72, 74, 76, 79]

# Full pentatonic ladder (C2..C6) used for register layering: the five Soul
# tracks are spread across distinct octaves so bass / harmony / melody do not
# collide in one low cluster.
PENTA = [p for p in range(36, 85) if p % 12 in (0, 2, 4, 7, 9)]

MAX_CONCURRENT = 6          # hard polyphony budget (prevents the v0.1 wall of sound)
SOUL_DURATION = 24.0        # seconds
PROGRESSIVE_CHAPTER = 6.0   # seconds per chapter (6 chapters -> 36 s)

# Hero / track catalog.  voice index -> role, human label, GM instrument.
VOICE_CATALOG = [
    dict(voice=0, role='melody',    name_zh='主旋律',  name_en='Melody · foreground curves',
         instrument='长笛',   program=73, color='#e0b357'),
    dict(voice=1, role='column',    name_zh='竖向立柱', name_en='Vertical columns',
         instrument='音乐盒', program=11, color='#69a9a3'),
    dict(voice=2, role='support',   name_zh='水平支撑', name_en='Horizontal support',
         instrument='大提琴', program=42, color='#8aa46f'),
    dict(voice=3, role='loop',      name_zh='闭环循环', name_en='Closed loops',
         instrument='氛围 Pad', program=88, color='#a98cc9'),
    dict(voice=4, role='accompany', name_zh='背景伴衬', name_en='Background · trees / texture',
         instrument='弦乐',   program=48, color='#c88972'),
]
ROLE_TO_VOICE = {c['role']: c['voice'] for c in VOICE_CATALOG}

# Progressive Revelation: introduce one geometry type at a time.
PROGRESSIVE_ORDER = ['melody', 'column', 'support', 'loop', 'accompany']
PROGRESSIVE_LABELS = [
    'Chapter 1 · 主旋律（前景曲线）单独进入',
    'Chapter 2 · + 竖向立柱（点状音轨）',
    'Chapter 3 · + 水平支撑（低音持续）',
    'Chapter 4 · + 闭环循环（氛围回响）',
    'Chapter 5 · + 背景伴衬（树林纹理）',
    'Chapter 6 · 全体合奏（完整画面）',
]

GEOMETRY_TYPES = ('curve', 'v_line', 'h_line', 'd_line', 'loop')
TYPE_LABELS = {
    'curve': '曲线 / 弧线',
    'v_line': '竖直线段',
    'h_line': '水平线段',
    'd_line': '斜向线段',
    'loop': '闭环轮廓',
}


# --------------------------------------------------------------------------
# Geometry classification
# --------------------------------------------------------------------------
def _pixel_length(points, w, h) -> float:
    a = np.asarray(points, float)
    if len(a) < 2:
        return 0.0
    seg = np.diff(a, axis=0) * np.array([w, h])
    return float(np.hypot(seg[:, 0], seg[:, 1]).sum())


def classify_units(paths, w: int, h: int):
    """Classify every extracted path into (geometry type, spatial layer).

    Returns (units, meta).  `units` keeps the source id + normalised points
    so the UI can trace a note back to the exact line it came from.
    """
    units = []
    for p in paths:
        pts = p.get('points') or []
        a = np.asarray(pts, float)
        if len(a) < 2:
            continue
        length = _pixel_length(pts, w, h)
        if length < 4:
            continue
        chord = float(np.hypot((a[-1, 0] - a[0, 0]) * w, (a[-1, 1] - a[0, 1]) * h))
        straight = chord / max(length, 1e-6)
        closed = chord < max(6.0, 0.05 * length) or (chord < 12.0 and length > 60.0)
        dx = (a[-1, 0] - a[0, 0]) * w
        dy = (a[-1, 1] - a[0, 1]) * h
        direction = math.degrees(math.atan2(dy, dx)) % 180.0
        cx = float(a[:, 0].mean())
        cy = float(a[:, 1].mean())
        centrality = 1.0 - min(1.0, math.hypot(cx - 0.5, cy - 0.5) / 0.7071)
        if closed:
            typ = 'loop'
        elif straight >= 0.86:
            if min(direction, 180.0 - direction) < 18.0:
                typ = 'h_line'
            elif abs(direction - 90.0) < 18.0:
                typ = 'v_line'
            else:
                typ = 'd_line'
        else:
            typ = 'curve'
        units.append(dict(
            id=p['id'], type=typ, points=pts,
            length=round(length, 2), straight=round(straight, 3),
            direction=round(direction, 1), closed=bool(closed),
            center=[round(cx, 5), round(cy, 5)], centrality=round(centrality, 4),
        ))

    # Spatial layer: subject = long AND central (the building); the rest is
    # background (trees, texture, distant detail).  45 % split, min 1 each.
    if units:
        lmax = max(u['length'] for u in units)
        for u in units:
            u['importance'] = round(0.6 * (u['length'] / lmax) + 0.4 * u['centrality'], 4)
        ranked = sorted(units, key=lambda u: -u['importance'])
        cut = max(1, int(len(units) * 0.45))
        subject_ids = {u['id'] for u in ranked[:cut]}
        for u in units:
            u['layer'] = 'subject' if u['id'] in subject_ids else 'background'
    else:
        subject_ids = set()

    by_type = {t: sum(1 for u in units if u['type'] == t) for t in GEOMETRY_TYPES}
    by_layer = {ly: sum(1 for u in units if u['layer'] == ly) for ly in ('subject', 'background')}
    meta = dict(total=len(units), by_type=by_type, by_layer=by_layer,
                subject=by_layer['subject'], background=by_layer['background'])
    return units, meta


# --------------------------------------------------------------------------
# Sampling + voice assignment
# --------------------------------------------------------------------------
def sample_path(points, count: int):
    """Sample `count` points by arc length (normalised coords)."""
    a = np.asarray(points, float)
    if len(a) < 2:
        return [a[0].tolist()] if len(a) else []
    d = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(a, axis=0), axis=1))]
    if d[-1] <= 1e-9:
        return [a[0].tolist()]
    if count <= 1:
        pos = [d[-1] / 2.0]
    else:
        pos = np.linspace(0.0, d[-1], count)
    return [[float(np.interp(v, d, a[:, i])) for i in range(2)] for v in pos]


def voice_for(unit: dict) -> int:
    """Public API: map a classified unit onto its voice index.

    Previously this was the private `_voice_for`, which other modules had to
    reach into (`build_studio.compact_units`).  The private alias is kept
    for backwards compatibility.
    """
    if 'user_voice' in unit:
        return unit['user_voice']
    if unit['layer'] == 'background':
        return ROLE_TO_VOICE['accompany']
    return {
        'v_line': ROLE_TO_VOICE['column'],
        'h_line': ROLE_TO_VOICE['support'],
        'loop': ROLE_TO_VOICE['loop'],
    }.get(unit['type'], ROLE_TO_VOICE['melody'])


# Backwards-compatible alias for older call sites.
_voice_for = voice_for


def _sample_count(unit: dict) -> int:
    if unit['type'] == 'curve':
        return 3
    if unit['type'] == 'loop':
        return 2
    return 1


def _duration_for(unit: dict) -> float:
    # length -> duration (Sonic Grammar: length -> note value)
    return round(float(np.clip(unit['length'] / 850.0, 0.18, 1.7)), 3)


def _build_candidates(units, voices_allowed, t0: float, t1: float, grid: float = 40.0):
    """Turn units into candidate notes inside [t0, t1).

    Spatial de-duplication (grid) keeps the printed shape even while the
    sounding budget stays small."""
    occupied = set()
    out = []
    span = max(t1 - t0, 1e-6)
    for u in units:
        v = _voice_for(u)
        if voices_allowed is not None and v not in voices_allowed:
            continue
        pts = sample_path(u['points'], _sample_count(u))
        if not pts:
            continue
        dur = _duration_for(u)
        center = float(np.mean([q[1] for q in pts]))
        span_y = max(0.12, max(q[1] for q in pts) - min(q[1] for q in pts))
        for j, q in enumerate(pts):
            key = (int(q[0] * grid), int(q[1] * grid), v)
            if key in occupied:
                continue
            occupied.add(key)
            if u['type'] == 'curve' and len(pts) > 1:
                raw = 13.0 * (1 - center) + 4.0 * (center - q[1]) / span_y
                method = 'local_contour'
            else:
                raw = 13.0 * (1 - q[1])
                method = 'height'
            ix = int(max(0, min(13, round(raw))))
            pitch = SCALE[ix]
            shift = 0
            if u['type'] == 'h_line':
                shift = -4
                pitch = SCALE[max(0, ix + shift)]
            start = t0 + q[0] * span
            vel = int(60 + 36 * (1 - q[1])) if u['layer'] == 'subject' else int(38 + 22 * (1 - q[1]))
            out.append(dict(
                unit=u, voice=v, pitch=pitch, start=start, duration=dur,
                velocity=max(1, min(127, vel)),
                point=[round(float(q[0]), 6), round(float(q[1]), 6)],
                calculation=dict(y=round(float(q[1]), 4), center=round(center, 4),
                                 span=round(span_y, 4), raw_degree=round(float(raw), 3),
                                 scale_index=ix, support_shift=shift, method=method),
            ))
    out.sort(key=lambda c: (c['start'], c['voice'], c['unit']['id']))
    return out


def _schedule(candidates, limit_end: float, max_concurrent: int = MAX_CONCURRENT):
    """Greedy scheduler with a HARD concurrency cap.

    Candidates are processed in ascending desired start.  For each one we
    find the earliest time >= its desired start at which fewer than
    `max_concurrent` notes are sounding and no same voice+pitch is still
    ringing.

    Performance (M3)
    -----------------
    The previous implementation kept *every* accepted note in a heap and
    scanned the whole heap for every candidate, which is O(n²).  On dense
    blueprints (12 000+ symbols) this was the dominant CPU cost of the
    whole pipeline.

    The scheduler now uses a **sliding window** over the accepted notes.
    A note can only be sounding at time `t` when it started no earlier
    than `t - max_duration` (every note is shorter than that), so the
    window `(t - max_duration, t]` contains every note that could possibly
    conflict.  The accepted notes are kept in a list ordered by start
    time, so the window bounds are found with two binary searches and only
    the notes inside the window are inspected.  The result is O(n log n)
    plus the (small) window size instead of O(n²).

    Exactness
    ---------
    The window is a strict superset of the old "sounding" set and the
    membership test is the same inequality, so the produced schedule is
    identical to the previous implementation.  This is verified by
    `test_scheduler.py`, which keeps the original algorithm as a reference
    oracle and compares the two on randomised inputs.

    Termination
    -----------
    The probe loop stops as soon as the candidate can no longer fit before
    `limit_end`; the old code kept probing for up to 4 000 iterations
    only to reject the candidate anyway.  The 4 000-iteration guard is
    kept as a second safety net.
    """
    import bisect

    accepted = []
    # Accepted notes ordered by their scheduled start time.
    order = []            # sorted list of (start, seq)
    notes = {}            # seq -> (end, voice, pitch)
    seq = 0

    # Longest note duration: the sliding window never has to look further
    # back than this.
    max_duration = 0.0
    for c in candidates:
        d = float(c['duration'])
        if d > max_duration:
            max_duration = d

    for c in candidates:
        s = float(c['start'])
        dur = float(c['duration'])
        v = int(c['voice'])
        p = int(c['pitch'])

        t = s
        for _ in range(4000):
            # The probe time only moves forward inside a candidate, so once
            # the candidate no longer fits into the window it is rejected.
            if t + dur > limit_end - 0.05:
                break
            # Every note that could still be sounding at `t` started inside
            # this window.
            lo = bisect.bisect_left(order, (t - max_duration, -1))
            hi = bisect.bisect_right(order, (t + 1e-9, float('inf')))
            active = 0
            clash = False
            earliest = None
            for start, nid in order[lo:hi]:
                end, voice, pitch = notes[nid]
                if end <= t + 1e-9:
                    continue                      # already stopped
                active += 1
                if earliest is None or end < earliest:
                    earliest = end
                if voice == v and pitch == p:
                    clash = True
            if active < max_concurrent and not clash:
                break
            if earliest is None or earliest <= t + 1e-9:
                t += 0.05
            else:
                t = earliest
        if t + dur > limit_end - 0.05:
            continue
        c['start'] = round(t, 3)
        seq += 1
        notes[seq] = (t + dur, v, p)
        bisect.insort(order, (t, seq))
        accepted.append(c)
    return accepted
def _to_notes(candidates, mode: str):
    notes = []
    for c in candidates:
        u = c['unit']
        key = f"{mode}:{u['id']}:{c['start']}:{c['voice']}:{c['pitch']}"
        notes.append(dict(
            id=hashlib.sha256(key.encode()).hexdigest()[:16],
            source=u['id'], source_point=c['point'], pitch=c['pitch'],
            start=c['start'], duration=c['duration'], rule=u['type'], voice=c['voice'],
            program=VOICE_CATALOG[c['voice']]['program'], velocity=c['velocity'],
            layer=u['layer'], type=u['type'], calculation=c['calculation'],
        ))
    return sorted(notes, key=lambda n: (n['start'], n['id']))


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def compose_units(units, mode: str = 'soul', style_key: str = 'east'):
    """Compose the full classified geometry into a traceable note list.

    `style_key` selects the harmony style of the Soul composition:

      * ``'east'`` — pentatonic, open / quartal voicings (the default),
      * ``'west'`` — functional major-key triads and sevenths.

    M8: the ``'west'`` style was fully implemented (chords, progressions,
    scale) but no call site could ever reach it, so roughly a dozen lines
    of carefully written harmony data were never exercised.  The style is
    now selectable, and `soul_composition.STYLES` remains the single
    source of truth for the available keys.
    """
    if mode == 'progressive':
        from soul_composition import compose
        from progressive_arrangement import arrange
        return arrange(compose(units, __import__(__name__), style_key), units=units)
    if mode == 'progressive_legacy':
        notes = []
        phases = []
        # 6 chapters; chapter k enables the first k types, chapter 6 = all.
        for ci in range(len(PROGRESSIVE_LABELS)):
            enabled_roles = PROGRESSIVE_ORDER if ci == len(PROGRESSIVE_LABELS) - 1 \
                else PROGRESSIVE_ORDER[:ci + 1]
            voices = {ROLE_TO_VOICE[r] for r in enabled_roles}
            t0 = ci * PROGRESSIVE_CHAPTER
            t1 = (ci + 1) * PROGRESSIVE_CHAPTER
            cands = _build_candidates(units, voices, t0, t1)
            notes.extend(_to_notes(_schedule(cands, t1), f'progressive{ci}'))
            phases.append(dict(start=t0, end=t1, roles=enabled_roles,
                               label=PROGRESSIVE_LABELS[ci]))
        duration = PROGRESSIVE_CHAPTER * len(PROGRESSIVE_LABELS)
        return dict(notes=sorted(notes, key=lambda n: (n['start'], n['id'])),
                    duration=duration, phases=phases,
                    voice_catalog=VOICE_CATALOG, version='studio-0.5')

    from soul_composition import compose
    return compose(units, __import__(__name__), style_key)


def overlap_peak(notes) -> int:
    """Maximum number of simultaneously sounding notes.

    Public API (previously the private `_overlap_peak`).  It is a small,
    dependency-free measurement helper that the regression tests use to
    assert the hard polyphony budget; it lives here so that the test
    module does not have to reach into a private symbol.
    """
    # Round to microseconds so a note's end ties with another's start and
    # is processed as an "off" before the next "on" (avoid float drift).
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


# Backwards-compatible alias for older call sites.
_overlap_peak = overlap_peak
