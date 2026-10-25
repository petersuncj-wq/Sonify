"""Build the traceable three-mode product UI from templates and real geometry.

v0.5 — high-coverage blueprint + soul.

  Blueprint : every skeleton sample is played as one integrated performance
              (5 instrument bands) with a full-width left-to-right scan; the
              UI reads `blueprint.audio` + `art[].band` + `art[].start`.
  Soul      : the full geometry is classified (curve / vertical / horizontal
              / loop / background) and every class becomes its own
              instrument track, scheduled under a hard polyphony budget.
"""
from pathlib import Path
import json
import shutil
import math
import struct
import wave
import numpy as np

import studio_grammar as sg
import compose_blueprint as cbp
import render_soundfont as rsf
from midi_io import write_midi

ROOT = Path(__file__).parent
OUT = ROOT / 'dist'
ASSETS = OUT / 'studio'
ASSETS.mkdir(exist_ok=True)

BLUEPRINT_VARIANT = 'H_mixed'   # balanced chamber palette for the full-score mix
# Blueprint uses its own 5 instrument bands (roof/body/sky/vert/curve); give
# them their own labels + colours so the UI does not confuse them with the
# Soul tracks.
BP_BAND_LABELS = ['屋顶 · 横线 Roof', '中段 · 弦乐 Body', '下方 · 铃 Sky',
                  '竖向 · 木琴 Vertical', '斜线 · 独奏 Curve']
BP_BAND_COLORS = ['#c98a3a', '#5f9ea0', '#8aa46f', '#b06a8f', '#9b8fc9']


def export_midi(notes, path, tempo_bpm=120, pans=None):
    """Thin wrapper kept for the many call sites across `photo/intake`.

    The real implementation now lives in `midi_io.write_midi`.
    """
    return write_midi(notes, path, tempo_bpm=tempo_bpm, pans=pans)


def art_symbols(bp):
    """Spatially thinned symbols used for drawing; each still a real skeleton
    sample.  We also tag its instrument band so the UI can colour it."""
    lengths = {p['id']: sum(math.hypot((b[0] - a[0]) * bp['source_width'],
                                        (b[1] - a[1]) * bp['source_height'])
                            for a, b in zip(p['points'], p['points'][1:]))
               for p in bp['paths']}
    occupied = set()
    out = []
    for n in bp['symbols']:
        cell = (int(n['x'] * bp['source_width'] / 8), int(n['y'] * bp['source_height'] / 8))
        if cell in occupied:
            continue
        if lengths.get(n['path'], 0) < 9:
            continue
        occupied.add(cell)
        item = dict(id=n['id'], x=n['x'], y=n['y'],
                    start=n.get('start', n['x'] * 12.0),
                    pitch=n['pitch'], path=n['path'])
        item['band'] = cbp._voice_band(n)
        out.append(item)
    return out


def compact_units(units):
    return [dict(id=u['id'], voice=sg._voice_for(u), type=u['type'],
                 layer=u['layer'], length=u['length']) for u in units]


def export_spatial_mix(stem_prefix, music):
    """Stereo reference mix of the same stems, equal-power pans and track gains."""
    mixed=None
    for v,(gain,pan) in enumerate(zip([.38,.18,.25,.14,.12],music['spatial_pan'])):
        with wave.open(str(ASSETS/f'{stem_prefix}-{v}.wav'),'rb') as f:
            rate=f.getframerate()
            audio=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2').astype(np.float32)/32768
            mono=audio.reshape(-1,f.getnchannels()).mean(axis=1)
        if mixed is None:mixed=np.zeros((len(mono),2),np.float32)
        angle=(pan+1)*np.pi/4
        mixed[:,0]+=mono*gain*np.cos(angle)
        mixed[:,1]+=mono*gain*np.sin(angle)
    fade=min(int(rate*.4),len(mixed))
    mixed[-fade:]*=np.linspace(1,0,fade)[:,None]
    with wave.open(str(ASSETS/f'{stem_prefix}-mix.wav'),'wb') as f:
        f.setnchannels(2);f.setsampwidth(2);f.setframerate(rate)
        f.writeframes((np.clip(mixed,-.98,.98)*32767).astype('<i2').tobytes())


def main():
    manifest = []
    sf = rsf.find_soundfont()
    if not sf:
        raise RuntimeError('A local SoundFont is required for offline studio audio')
    pool = rsf._SoundFontPool.get(sf, rate=22050, gain=1.2)

    for i in range(6):
        raw = json.loads((OUT / f'sample{i}.json').read_text(encoding='utf-8'))
        bp = json.loads((OUT / f'sample{i}-blueprint.json').read_text(encoding='utf-8'))

        units, unit_meta = sg.classify_units(bp['paths'], bp['source_width'], bp['source_height'])
        art = art_symbols(bp)

        payload = dict(
            id=raw['id'], name=raw['name'], exclusions=raw['exclusions'],
            width=bp['source_width'], height=bp['source_height'],
            art=art, contours=bp['paths'], dense_count=len(bp['symbols']),
            drawn_count=len(art), source_hash=raw['sha256'],
            units=compact_units(units), unit_meta=unit_meta,
            voice_catalog=sg.VOICE_CATALOG,
        )

        # ---- Blueprint: the whole building performed at once --------------
        bp_notes = cbp.compose_blueprint(bp, BLUEPRINT_VARIANT, total_seconds=13.0)
        audible_bp = [n for v in range(5)
                      for n in rsf._thin_voice(
                          [n for n in bp_notes if n['voice'] == v], 40)]
        audible_ids = {n['id'] for n in audible_bp}
        bp_by_id = {n['id']: n for n in bp_notes}
        for symbol in art:
            note = bp_by_id[symbol['id']]
            symbol['raw_pitch'] = symbol['pitch']
            symbol['pitch'] = note['pitch']
            symbol['duration'] = note['duration']
            symbol['audible'] = symbol['id'] in audible_ids
        bp_wav = ASSETS / f'sample{i}-blueprint.wav'
        rsf.render_blueprint_soundfont(bp_notes, bp_wav, sf_path=sf,
                                       total_seconds=13.0, rate=22050, gain=1.2,
                                       pool=pool)
        export_midi(audible_bp, ASSETS / f'sample{i}-blueprint.mid')
        vcount = {}
        for n in audible_bp:
            vcount[n['voice']] = vcount.get(n['voice'], 0) + 1
        bp_progs = cbp._programs(BLUEPRINT_VARIANT)
        bp_insts = cbp._instrument_names(BLUEPRINT_VARIANT)
        payload['blueprint'] = dict(
            audio=f'studio/sample{i}-blueprint.wav', variant=BLUEPRINT_VARIANT,
            duration=13.0, notes=len(audible_bp),
            candidate_notes=len(bp_notes), symbols=len(bp['symbols']),
            drawn=len(art),
            voices=[dict(voice=v, label=BP_BAND_LABELS[v], instrument=bp_insts[v],
                         program=bp_progs[v], color=BP_BAND_COLORS[v],
                         notes=vcount.get(v, 0)) for v in range(5)],
        )

        # ---- Soul + Progressive: full geometry, per-voice stems ----------
        for mode in ['soul', 'progressive']:
            music = sg.compose_units(units, 'progressive_legacy' if mode=='progressive' else mode)
            payload[mode] = music
            for v in range(5):
                ns = [n for n in music['notes'] if n['voice'] == v]
                rsf.render_wav(ns, ASSETS / f'sample{i}-{mode}-{v}.wav',
                               sf_path=sf, total_seconds=music['duration'] + 1.0,
                               rate=22050, pool=pool)
            export_midi(music['notes'], ASSETS / f'sample{i}-{mode}.mid', music.get('tempo', 120),music.get('spatial_pan'))
            if mode=='soul':export_spatial_mix(f'sample{i}-soul',music)

        from soul_composition import make_demo_cut
        demo_music=make_demo_cut(payload['soul'])
        payload['soul_demo']=demo_music
        for v in range(5):
            rsf.render_wav([n for n in demo_music['notes'] if n['voice']==v],
                           ASSETS / f'sample{i}-soul-demo-{v}.wav',sf_path=sf,
                           total_seconds=demo_music['duration']+1,rate=22050,pool=pool)
        export_midi(demo_music['notes'],ASSETS / f'sample{i}-soul-demo.mid',demo_music['tempo'],demo_music['spatial_pan'])
        export_spatial_mix(f'sample{i}-soul-demo',demo_music)

        (ASSETS / f'sample{i}.json').write_text(
            json.dumps(payload, ensure_ascii=False, separators=(',', ':')),
            encoding='utf-8')
        manifest.append(dict(id=raw['id'], name=raw['name']))
        print(raw['id'], 'units', len(units), unit_meta['by_type'],
              '| art', len(art), '| soul', len(payload['soul']['notes']),
              '| progressive', len(payload['progressive']['notes']),
              '| blueprint', len(bp_notes))

    (ASSETS / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False),
                                          encoding='utf-8')
    for name in ['studio.html', 'studio.css', 'studio.js', 'soul_experience.js', 'soul_interaction.js', 'soul_hero.js', 'progressive_revelation.js']:
        shutil.copyfile(ROOT / 'ui' / name, OUT / name)
    # Preserve the v3 experiment page and expose the new product view.
    p = OUT / 'lab-v3.html'
    if p.exists():
        s = p.read_text(encoding='utf-8')
        if 'studio.html' not in s:
            s = s.replace('<div class="topnav">',
                          '<div class="topnav"><a href="studio.html">新版创作界面 ↗</a> ')
            p.write_text(s, encoding='utf-8')
    from build_progressive_arrangement import build as build_progressive
    build_progressive()
    pool.close()


if __name__ == '__main__':
    main()
