"""Soul Symphony v0.8 — anchor notes, phrase development, harmony planner.

Implements the P0 items of the "Soul Symphony v2.0 工程整改任务书":

  P0.1  Anchor notes   — the melody keeps the geometry-derived contour notes as
        *anchors* (note_role='anchor'); every added note is tagged as
        variation / harmony / ornament and links back to its parent anchor.
  P0.2  Phrase Development Engine — the geometric motif is presented, answered,
        fragmented, augmented and recapitulated across A / B / C / A′, with real
        rests (breathing) and call-and-answer between voices.
  P0.3  Harmony Planner — a chord progression per section, smooth voice leading,
        inversions, and half / authentic cadences. Two styles: 'east' (pentatonic
        open/quartal voicings) and 'west' (functional major-key triads/sevenths).
  P0.4  Five real voice roles — melody / rhythm-response / bass / harmony / ambience.
  P0.5  Four differentiated sections (no volume-only faking).

Everything is deterministic and traceable:
anchor(source_geometry, contour) -> motif -> phrase -> section -> arrangement.
"""
from __future__ import annotations

import hashlib

TEMPO = 92
BEAT = 60.0 / TEMPO
BAR = BEAT * 4
SECTIONS = 4
BARS_PER_SECTION = 8
DURATION = BAR * SECTIONS * BARS_PER_SECTION

SECTION_ORDER = {'A': 0, 'B': 1, 'C': 2, 'A′': 3}

# Register (音区) windows are expressed as *ratios* of the active scale
# ladder instead of hard-coded absolute MIDI numbers.  The old absolute
# table was silently coupled to `grammar.PENTA` (36..84): changing the
# ladder start made `_in_win()` return an empty list, `_chord_pitches()`
# fall back to an empty list too, and the whole voice went silent without
# raising anything.  Ratios keep the registers valid for any ladder.
REGISTER_RATIOS = {
    0: (0.75, 1.00),   # melody    — top of the ladder
    1: (0.60, 0.76),   # rhythm    — upper-middle
    2: (0.00, 0.28),   # bass      — bottom
    3: (0.27, 0.52),   # harmony   — lower-middle
    4: (0.42, 0.68),   # ambience  — middle
}
# Absolute fallback windows, used only when the ladder is degenerate.
REGISTER = {0: (69, 84), 1: (63, 70), 2: (38, 48), 3: (48, 59), 4: (55, 66)}
REG_OFFSET = {0: 7, 1: 3, 2: -9, 3: -4, 4: -1}


def _register_ranges(ladder):
    """Derive the per-voice register windows from the active scale ladder.

    The windows are proportional slices of `ladder`, so they remain valid
    whatever the ladder's range happens to be (pentatonic `PENTA`, the
    `west` chromatic ladder, or a future re-tuned ladder).
    """
    if not ladder:
        raise ValueError('scale ladder is empty; cannot derive register windows')
    lo, hi = float(ladder[0]), float(ladder[-1])
    span = hi - lo
    if span <= 0:
        span = 1.0
    ranges = {}
    for voice, (a, b) in REGISTER_RATIOS.items():
        ranges[voice] = (lo + span * a, lo + span * b)
    return ranges

# ---- styles ---------------------------------------------------------------
STYLES = {
    'east': dict(
        name='东方自然 · 五声开放式',
        pcs=(0, 2, 4, 7, 9),
        chords={'I': (0, {0, 4, 7}), 'vi': (9, {9, 0, 4}), 'IV': (2, {2, 7, 9}),
                'V': (7, {7, 2, 4}), 'ii': (2, {2, 7, 0}), 'iii': (4, {4, 9, 0})},
        prog={'A':  ['I', 'I', 'vi', 'IV', 'I', 'V', 'vi', 'I'],
              'B':  ['vi', 'IV', 'V', 'V', 'vi', 'ii', 'V', 'V'],
              'C':  ['IV', 'V', 'I', 'vi', 'IV', 'V', 'iii', 'ii'],
              'A′': ['I', 'vi', 'IV', 'V', 'I', 'IV', 'V', 'I']},
    ),
    'west': dict(
        name='西洋古典 · 功能和声',
        pcs=(0, 2, 4, 5, 7, 9, 11),
        chords={'I': (0, {0, 4, 7}), 'ii': (2, {2, 5, 9}), 'iii': (4, {4, 7, 11}),
                'IV': (5, {5, 9, 0}), 'V': (7, {7, 11, 2}), 'V7': (7, {7, 11, 2, 5}),
                'vi': (9, {9, 0, 4})},
        prog={'A':  ['I', 'vi', 'IV', 'V', 'I', 'vi', 'IV', 'V'],
              'B':  ['ii', 'V7', 'I', 'vi', 'ii', 'V7', 'I', 'V7'],
              'C':  ['vi', 'iii', 'IV', 'V7', 'vi', 'iii', 'IV', 'V7'],
              'A′': ['I', 'vi', 'IV', 'V', 'I', 'IV', 'V7', 'I']},
    ),
}

SECTION_META = [
    ('A',  '主题初现', '几何主题以锚定音陈述，低音与和声轻声进入'),
    ('B',  '层间对话', '对比动机与主旋律问答，低音与和声开始转换'),
    ('C',  '结构共鸣', '动机拆解发展、声部加密，推向高潮'),
    ('A′', '主题归来', '锚定主题回归，配器更丰满，V→I 终止收束'),
]
SECTION_VOICES = {'A': [0, 2, 4], 'B': [0, 1, 2], 'C': [0, 1, 2, 3, 4], 'A′': [0, 2, 3, 4]}
# visual-structure role per voice (for the Geometry -> Music legend / syncing)
VOICE_STRUCTURE = {0: 'spine', 1: 'pattern', 2: 'support', 3: 'support', 4: 'texture'}
STRUCTURES = [
    dict(id='spine',   label='主体结构', en='Subject Spine',   role='主旋律', voice=0),
    dict(id='pattern', label='重复结构', en='Pattern Field',   role='节奏织体', voice=1),
    dict(id='support', label='支撑结构', en='Support Frame',   role='低音 / 和声', voice=2),
    dict(id='texture', label='背景纹理', en='Atmospheric',     role='环境氛围', voice=4),
]

# melody plan per section: 'M' = phrase bar, 'r' = rest (breathing), 'A' = augmented
MELODY_PLAN = {
    'A':  ['M', 'M', 'r', 'M', 'M', 'M', 'r', 'M'],   # 4-bar statement + response
    'B':  ['M', 'r', 'M', 'M', 'r', 'M', 'M', 'r'],   # dialogue, answered in the gaps
    'C':  ['M', 'M', 'M', 'M', 'A', 'M', 'M', 'A'],   # development + augmentation
    'A′': ['M', 'M', 'r', 'M', 'M', 'r', 'A', 'A'],   # breathe, then an audible cadence
}
RHYTHMS = [
    [(0, 1), (1, 1), (2, 1), (3, 1)],
    [(0, .5), (.5, .5), (1, 1), (2, 1), (3, .5)],
    [(0, 1.5), (1.5, .5), (2, 1), (3, 1)],
    [(0, 1), (1, .5), (1.5, .5), (2, 2)],
]
AUGMENTED = [(0, 2), (2, 2)]            # augmented (longer) statement
RHYTHM_PATTERN = [0, .5, 1.5, 2, 3, 3.5]


# --------------------------------------------------------------------------
def _ladder(grammar, style_key):
    pcs = STYLES[style_key]['pcs']
    if set(pcs) == {0, 2, 4, 7, 9}:
        return grammar.PENTA
    return [p for p in range(36, 85) if p % 12 in pcs]


def _in_win(ladder, lo, hi):
    return [p for p in ladder if lo <= p <= hi]


def _chord_pitches(ladder, pcs, lo, hi):
    """Chord tones of `pcs` inside [lo, hi].

    Raises `ValueError` when the window contains no chord tone.  The old
    implementation returned an empty list, and the caller then fell back to
    `_in_win()` — if that was empty too, the voice went completely silent
    without any error.  Failing loudly is the whole point of the fix.
    """
    tones = [p for p in ladder if lo <= p <= hi and p % 12 in pcs]
    if not tones:
        raise ValueError(
            f'no chord tones in register [{lo:.1f},{hi:.1f}] for pcs {sorted(pcs)}; '
            f'ladder range [{ladder[0] if ladder else "-"},{ladder[-1] if ladder else "-"}]')
    return tones


def _nearest_index(seq, value):
    return min(range(len(seq)), key=lambda i: abs(seq[i] - value))


def _contour_steps(ys):
    deltas = [b - a for a, b in zip(ys, ys[1:])]
    mx = max((abs(d) for d in deltas), default=0) or 1.0
    out, last = [], 1
    for d in deltas:
        if abs(d) < 0.004 * mx or d == 0:
            s = last
        else:
            mag = 2 if abs(d) >= 0.5 * mx else 1
            s = mag if d < 0 else -mag
        out.append(s)
        last = s
    return out


def _motif_degrees(ys, reverse=False):
    steps = _contour_steps(ys)
    picked = [steps[0], steps[2], steps[4], steps[6]]
    if reverse:
        picked = picked[::-1]
    deg = [0]
    for s in picked:
        deg.append(deg[-1] + s)
    return deg


def _voice_lead(ladder, pcs, lo, hi, prev, n):
    """Pick n chord tones inside [lo,hi] that move least from `prev`."""
    tones = _chord_pitches(ladder, pcs, lo, hi) or _in_win(ladder, lo, hi)
    if not tones:
        return []
    if not prev:
        centre = (lo + hi) / 2
        return sorted(tones, key=lambda p: abs(p - centre))[:n]
    chosen = []
    for i in range(n):
        ref = prev[i] if i < len(prev) else (sum(prev) / len(prev) if prev else tones[0])
        available = [p for p in tones if p not in chosen]
        if not available:
            break
        pick = min(available, key=lambda p: abs(p - ref))
        chosen.append(pick)
    return sorted(set(chosen))


def _stitch_curve(units, max_paths=8, max_gap=0.035):
    """Chain the longest paths of a group into ONE polyline (multi-path stitch).

    Returns a list of vertices, each carrying its owning path id/type/layer so a
    sampled note can still trace back to a real source path."""
    import math
    pool = sorted(units, key=lambda u: (-u['length'], u['id']))[:max_paths]
    if not pool:
        return []
    info = {u['id']: u for u in pool}
    pts = {u['id']: list(u['points']) for u in pool}

    def vert(pid, p):
        return dict(x=float(p[0]), y=float(p[1]), id=pid, type=info[pid]['type'],
                    layer=info[pid]['layer'], length=info[pid]['length'])

    used = {pool[0]['id']}
    chain = [vert(pool[0]['id'], p) for p in pts[pool[0]['id']]]
    end = (chain[-1]['x'], chain[-1]['y'])
    while len(used) < len(pool):
        best, bd, brev = None, 1e9, False
        for u in pool:
            if u['id'] in used:
                continue
            p = pts[u['id']]
            da = math.hypot(p[0][0] - end[0], p[0][1] - end[1])
            db = math.hypot(p[-1][0] - end[0], p[-1][1] - end[1])
            for distance, reverse in ((da,False),(db,True)):
                candidate = p[::-1] if reverse else p
                if len(candidate)<2 or distance>max_gap:
                    continue
                a=(chain[-1]['x']-chain[-2]['x'],chain[-1]['y']-chain[-2]['y'])
                b=(candidate[1][0]-candidate[0][0],candidate[1][1]-candidate[0][1])
                denom=math.hypot(*a)*math.hypot(*b)
                alignment=(a[0]*b[0]+a[1]*b[1])/denom if denom>1e-10 else 1
                if alignment < .35:
                    continue
                bridge=(candidate[0][0]-end[0],candidate[0][1]-end[1])
                if distance>.008 and math.hypot(*a)>1e-8:
                    if (bridge[0]*a[0]+bridge[1]*a[1])/(distance*math.hypot(*a)) < .3:
                        continue
                score=distance*(1.5-.5*alignment)
                if score<bd:
                    bd,best,brev=score,u['id'],reverse
        if best is None or bd > max_gap:
            break
        used.add(best)
        p = pts[best][::-1] if brev else pts[best]
        chain += [vert(best, q) for q in p]
        end = (chain[-1]['x'], chain[-1]['y'])
    return chain


def _sample_curve(curve, n, reverse=False):
    """Sample n vertices by arc length along a stitched curve."""
    c = curve[::-1] if reverse else curve
    if not c:
        return []
    if n <= 1:
        return [c[len(c) // 2]]
    acc, d = 0.0, [0.0]
    for a, b in zip(c, c[1:]):
        acc += ((b['x'] - a['x']) ** 2 + (b['y'] - a['y']) ** 2) ** .5
        d.append(acc)
    if acc <= 1e-9:
        return [c[0]] * n
    out = []
    j = 0
    for k in range(n):
        t = acc * k / (n - 1)
        while j < len(d) - 1 and d[j + 1] < t:
            j += 1
        out.append(c[j])
    return out


def compose(units, grammar, style_key='east'):
    # M8: the style key used to be looked up in `STYLES` without any
    # validation, so a typo raised a bare `KeyError` deep inside the
    # composer.  Validate explicitly and list the available keys.
    if style_key not in STYLES:
        raise ValueError(
            f"unknown harmony style {style_key!r}; available: {', '.join(sorted(STYLES))}"
        )
    style = STYLES[style_key]
    ladder = _ladder(grammar, style_key)
    chords = style['chords']
    prog = style['prog']
    # Register windows are derived from the *active* ladder, so a change of
    # scale (or of the ladder's range) can never silently mute a voice.
    registers = _register_ranges(ladder)

    groups = {}
    for u in units:
        x, y = u['center']
        v = grammar.voice_for(u)
        cell = (min(2, int(x * 3)), min(2, int(y * 3)), v)
        gid = ('user-' if 'user_voice' in u else 'g-') + '%s-%s-%s' % cell
        if 'user_region' in u:gid='user-region-%s-%s' % (u['user_region'],v)
        if gid not in groups:
            groups[gid] = dict(id=gid, voice=v, sources=[], units=[],
                               label=['左侧', '中部', '右侧'][cell[0]] + ['上层', '中层', '下层'][cell[1]],
                               layer=u['layer'], user_selected='user_voice' in u)
            if 'user_region' in u:
                groups[gid]['label']='自选区域 %s' % u['user_region_number']
                groups[gid]['region_id']=u['user_region']
        groups[gid]['sources'].append(u['id'])
        groups[gid]['units'].append(u)
    # Dense window ornament can have a huge total length. Give the lead role
    # to a long coherent contour instead of rewarding that texture density.
    pools = {v: sorted([g for g in groups.values() if g['voice'] == v],
                       key=lambda g: (not g.get('user_selected',False),
                                      -max(u['length'] for u in g['units']) if v==0 else -sum(u['length'] for u in g['units']),
                                      -sum(u['length'] for u in g['units'])) )
             for v in range(5)}

    notes, phrases, phases = [], [], []
    prev_harmony = []
    prev_bass = None
    cur_group_id = None
    group_usage={v:0 for v in range(5)}
    counted_phrases=set()

    def add(voice, src, pitch, beat, dur_beats, section, bar, role, calc, point,
            motif_id, transform, parent=None, base_vel=None):
        phrase_key=(section,bar,voice)
        if phrase_key not in counted_phrases:
            counted_phrases.add(phrase_key);group_usage[voice]+=1
        start = (SECTION_ORDER[section] * BARS_PER_SECTION + bar) * BAR + beat * BEAT
        dur = max(.05, min(dur_beats * BEAT, start // BAR * BAR + BAR - start - .03))
        bvel = base_vel if base_vel is not None else {0: 86, 1: 56, 2: 60, 3: 46, 4: 40}[voice]
        # phrase-level dynamic arc: A/B build, C is the climax, A′ eases to the cadence
        arc_base = {'A': -6, 'B': 0, 'C': 13, 'A′': 4}[section]
        arc_slope = {'A': 5, 'B': 6, 'C': 10, 'A′': -13}[section]
        dyn = round(arc_base + arc_slope * (bar / (BARS_PER_SECTION - 1))) + (4 if beat == 0 else 0)
        notes.append(dict(
            id=hashlib.sha256(f"{src['id']}-{section}-{bar}-{voice}-{beat}-{pitch}".encode()).hexdigest()[:16],
            source=src['id'], source_point=[round(z, 6) for z in point],
            pitch=int(pitch), start=round(start, 6), duration=round(dur, 6),
            rule=src['type'], voice=voice, program=grammar.VOICE_CATALOG[voice]['program'],
            velocity=max(1, min(127, bvel + dyn)),
            layer=src['layer'], type=src['type'], role=role,
            note_role=role, structure=VOICE_STRUCTURE[voice],
            motif_id=motif_id, section_id=section, voice_id=voice,
            parent_note_id=parent, phrase=f'{section}-{bar}-{voice}', group=cur_group_id,
            section=section, calculation=calc,
        ))

    # ------------------------------------------------------------------ notes
    for si, (letter, title, story) in enumerate(SECTION_META):
        phases.append(dict(id=letter, label=letter + ' · ' + title, description=story,
                           start=round(si * BARS_PER_SECTION * BAR, 6),
                           end=round((si + 1) * BARS_PER_SECTION * BAR, 6)))
        voices = SECTION_VOICES[letter]
        last_bar = BARS_PER_SECTION - 1
        for bi in range(BARS_PER_SECTION):
            chord_name = prog[letter][bi]
            root_pc, pcs = chords[chord_name]
            bar_start = (si * BARS_PER_SECTION + bi) * BAR

            # one HERO motif per voice, then transformed per section
            # (motif transformation, not a different group each bar)
            for v in voices:
                pool = pools[v]
                if not pool:
                    continue
                user_groups=[g for g in pool if g.get('user_selected')]
                group=user_groups[group_usage[v]%len(user_groups)] if user_groups else pool[0]
                curve = _stitch_curve(group['units'])
                if not curve:
                    continue
                motif_id = 'motif-' + group['id']
                cur_group_id = group['id']
                pid = f'{letter}-{bi}-{v}'
                transform = {'A': '原形', 'B': '逆行', 'C': '展开', 'A′': '回归'}[letter]
                phrases.append(dict(id=pid, group=group['id'], voice=v,
                                    start=round(bar_start, 6), end=round(bar_start + BAR, 6),
                                    section=letter, motif=motif_id, transform=transform,
                                    sources=group['sources'], chord=chord_name))
                def calc(method, y, center, span, raw, ix, var_shift, final_ix, src, bar=bi, beat=0, chord=chord_name):
                    return dict(method=method, y=round(y, 4), center=round(center, 4),
                                span=round(span, 4), raw_degree=round(raw, 3),
                                scale_index=int(max(0, min(13, round(raw)))),
                                support_shift=REG_OFFSET[v], variation_shift=var_shift,
                                final_index=int(final_ix), transform=transform,
                                length_factor=round(.85 + .3 * min(1, src['length'] / 250), 4),
                                bar=si * 8 + bar + 1, beat=beat, chord=chord)

                # ---------------- melody (v0): anchors + phrase development
                if v == 0:
                    plan = MELODY_PLAN[letter][bi]
                    if plan == 'r':
                        continue
                    samples = _sample_curve(curve, 8, reverse=(letter == 'B'))
                    ys = [s['y'] for s in samples]
                    mu = sum(ys) / len(ys)
                    sp = max(.12, max(ys) - min(ys))
                    deg = _motif_degrees(ys)
                    if letter == 'C':      # fragment / reorder the motif
                        deg = [deg[0], deg[2 % len(deg)], deg[4 % len(deg)],
                               deg[1 % len(deg)], deg[3 % len(deg)]]
                    lift = 5 if (letter == 'A′' and bi == BARS_PER_SECTION - 1) else 0
                    tones = _chord_pitches(ladder, pcs, *registers[0])
                    centre = sum(registers[0]) / 2
                    base = _nearest_index(ladder, min(tones, key=lambda p: abs(p - centre)))
                    tmpl = AUGMENTED if plan == 'A' else RHYTHMS[bi % len(RHYTHMS)]
                    final_beat = tmpl[-1][0]
                    # A / A′ state the geometry anchor; B / C develop it (variation)
                    mel_role = 'anchor' if letter in ('A', 'A′') else 'variation'
                    for k, (beat, dur) in enumerate(tmpl):
                        idx = max(0, min(len(ladder) - 1, base + deg[k % len(deg)] + lift))
                        pitch = ladder[idx]
                        if letter == 'A′' and bi == last_bar and beat == final_beat:
                            lo_m, hi_m = registers[0]
                            cadence = [p for p in ladder if p % 12 == 0 and lo_m <= p <= hi_m]
                            pitch = min(cadence, key=lambda p: abs(p - (lo_m + hi_m) / 2))
                            idx = ladder.index(pitch)
                        if beat == 0 or beat == final_beat:
                            cts = _chord_pitches(ladder, pcs, *registers[0])
                            idx = _nearest_index(ladder, min(cts, key=lambda p: abs(p - pitch)))
                            pitch = ladder[idx]
                        s = samples[min(k, len(samples) - 1)]
                        raw = 13.0 * (1 - mu) + 4.0 * (mu - s['y']) / sp
                        add(0, s, pitch, beat, dur, letter, bi, mel_role,
                            calc('motif_contour', s['y'], mu, sp, raw, idx, 0, idx, s),
                            [s['x'], s['y']], motif_id, transform)
                    continue

                head = _sample_curve(curve, 1)[0]

                # ---------------- rhythm response (v1): Q&A, not a copy
                if v == 1:
                    if letter == 'B' and MELODY_PLAN['B'][bi] == 'M':
                        continue                      # stay quiet when the melody speaks
                    tones = _chord_pitches(ladder, pcs, *registers[1])
                    pattern = RHYTHM_PATTERN if letter == 'C' and bi%2 else [0,1.5,3]
                    for j, beat in enumerate(pattern):
                        pitch = tones[(j + bi) % len(tones)]
                        add(1, head, pitch, beat, .45, letter, bi, 'ornament',
                            calc('chord_tone', .5, .5, .12, 0, 0, 0, ladder.index(pitch), head),
                            [head['x'], head['y']], motif_id, transform)
                    continue

                # ---------------- bass (v2): root with stepwise connection
                if v == 2:
                    cwin = _chord_pitches(ladder, pcs, *registers[2])
                    roots = [p for p in ladder if registers[2][0] <= p <= registers[2][1] and p % 12 == root_pc]
                    root = min(roots or cwin, key=lambda p: abs(p - (prev_bass if prev_bass is not None else cwin[0])))
                    prev_bass = root
                    fifths = [p for p in cwin if p != root]
                    fifth = min(fifths, key=lambda p: abs(p - root - 7)) if fifths else root
                    plan = [(0, root, 3.5)] if letter == 'A' else [(0, root, 1.6), (2, fifth, 1.6)]
                    if letter == 'C':
                        nxt = prog[letter][min(last_bar, bi + 1)]
                        npc = chords[nxt][0]
                        targets = [p for p in ladder if registers[2][0] <= p <= registers[2][1] and p % 12 == npc]
                        target = min(targets or [root], key=lambda p: abs(p - fifth))
                        plan = [(0, root, 1.4), (1.5, fifth, 1.1), (3, target, .85)]
                    if letter=='A′' and bi>=5: plan=[(0,root,3.85)]
                    for beat, bass_pitch, length in plan:
                        add(2, head, bass_pitch, beat, length, letter, bi, 'harmony',
                            calc('chord_root', .5, .5, .12, 0, 0, 0, ladder.index(bass_pitch), head),
                            [head['x'], head['y']], motif_id, transform)
                    continue

                # ---------------- harmony (v3): voice-led chord bed
                if v == 3:
                    count=3 if letter=='A′' and bi==last_bar else 2
                    voicing = _voice_lead(ladder, pcs, *registers[3], prev_harmony, count)
                    prev_harmony = voicing
                    for pitch in voicing:
                        add(3, head, pitch, 0, 3.94, letter, bi, 'harmony',
                            calc('voice_leading', .5, .5, .12, 0, 0, 0, ladder.index(pitch), head),
                            [head['x'], head['y']], motif_id, transform)
                    continue

                # ---------------- ambience (v4): open tone, changes per section
                if (letter=='A' and bi%2) or (letter=='A′' and bi in (4,5)):
                    continue
                tones = _chord_pitches(ladder, pcs, *registers[4])
                pitch = tones[0]
                add(4, head, pitch, 0, 3.94, letter, bi, 'ambient',
                    calc('open_voicing', .5, .5, .12, 0, 0, 0, ladder.index(pitch), head),
                    [head['x'], head['y']], motif_id, transform)

    # release overlapping retriggers on the same voice+pitch
    previous = {}
    for note in sorted(notes, key=lambda n: n['start']):
        key = (note['voice'], note['pitch'])
        prior = previous.get(key)
        if prior and prior['start'] + prior['duration'] >= note['start']:
            prior['duration'] = round(max(.02, note['start'] - prior['start'] - .02), 6)
        previous[key] = note
    # keep monophonic parts (melody / rhythm / bass / ambience) from overlapping
    for v in (0, 1, 2, 4):
        seq = sorted([n for n in notes if n['voice'] == v], key=lambda n: (n['start'], n['pitch']))
        for a, b in zip(seq, seq[1:]):
            if a['start'] + a['duration'] > b['start']:
                a['duration'] = round(max(.02, b['start'] - a['start'] - .005), 6)

    public_groups = [{k: val for k, val in g.items() if k not in ('units','user_selected')} for g in groups.values()]
    structures = []
    for s in STRUCTURES:
        vs = [2, 3] if s['id'] == 'support' else [s['voice']]
        gids = set()
        for v in vs:
            if pools.get(v):
                chosen_groups=[g for g in pools[v] if g.get('user_selected')] or pools[v][:1]
                for g in chosen_groups:gids.update(g['sources'])
        structures.append(dict(id=s['id'], label=s['label'], en=s['en'], role=s['role'],
                               voice=s['voice'],
                               color=grammar.VOICE_CATALOG[s['voice']]['color'],
                               geometry_ids=sorted(gids)))
    return dict(notes=sorted(notes, key=lambda n: (n['start'], n['id'])),
                duration=DURATION, phases=phases, groups=public_groups, phrases=phrases,
                structures=structures,
                tempo=TEMPO, style=style_key, style_name=style['name'],
                spatial_pan=[-.12,.32,-.08,-.3,.42],
                voice_catalog=[dict(v, name_zh=['主旋律', '节奏回应', '低音支撑', '和声铺陈', '环境织体'][v['voice']])
                               for v in grammar.VOICE_CATALOG],
                version='soul-1.1', bars=32,
                region_method='主体结构由几何显著性自动提取；其余按视觉组织分工归类')


def make_demo_cut(music):
    """18 bars / 46.96 s, with a complete four-section arc and final cadence.

    Copy real sections, preserving IDs and provenance. Timing is the only
    transformation; source_time records the position in the full composition.
    """
    from copy import deepcopy
    out=deepcopy(music)
    selections=[('A',0,4),('B',0,4),('C',2,8),('A′',4,8)]
    notes,phrases,phases=[],[],[]
    cursor=0.0
    for section, first, last in selections:
        si=SECTION_ORDER[section]
        begin=(si*8+first)*BAR; end=(si*8+last)*BAR
        shift=cursor-begin
        phase=deepcopy(next(p for p in music['phases'] if p['id']==section))
        phase.update(start=round(cursor,6),end=round(cursor+end-begin,6))
        phases.append(phase)
        for original in music['notes']:
            if begin-1e-5<=original['start']<end-1e-5:
                n=deepcopy(original);n['source_time']=n['start']
                n['start']=round(n['start']+shift,6)
                n['duration']=round(min(n['duration'],phase['end']-n['start']),6)
                n['calculation']['full_bar']=n['calculation']['bar']
                n['calculation']['bar']=int(round(cursor/BAR))+(original['calculation']['bar']-si*8-first)
                notes.append(n)
        for original in music['phrases']:
            if begin-1e-5<=original['start']<end-1e-5:
                p=deepcopy(original);p['start']=round(p['start']+shift,6);p['end']=round(p['end']+shift,6)
                phrases.append(p)
        cursor+=end-begin
    out.update(notes=notes,phrases=phrases,phases=phases,duration=round(cursor,6),bars=18,
               edition='demo',version=music['version']+'-demo')
    return out
