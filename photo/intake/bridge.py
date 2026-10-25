"""Build one uploaded image in a private workspace using existing Photo engines.

Runs in a subprocess: module globals and SoundFont state cannot affect the
ongoing Photo build. No original source, manifest, sample or audio is changed.
"""
from pathlib import Path
import hashlib
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parent
EXPERIMENT = ROOT.parent / 'experiment'
sys.path[:0] = [str(EXPERIMENT / 'vendor'), str(EXPERIMENT)]
from engine_snapshot import EngineSnapshot
ENGINE = EngineSnapshot(EXPERIMENT).install()
import numpy as np
from PIL import Image
import blueprint
import build_studio as studio
import studio_grammar as grammar
import compose_blueprint as composer
import render_soundfont as renderer
from soul_composition import make_demo_cut
import on_demand_render as on_demand


def build(folder, soul_style='east'):
    folder = Path(folder).resolve()
    hashes = ENGINE.hashes
    workspace = folder / 'workspace'
    assets = workspace / 'studio'
    assets.mkdir(parents=True, exist_ok=True)
    studio.OUT, studio.ASSETS = workspace, assets
    sf = renderer.find_soundfont()
    if not sf:
        raise RuntimeError('没有找到现有音乐渲染所需的 SoundFont。')
    skeleton = np.array(Image.open(folder / 'skeleton.png').convert('L'))
    bp = blueprint.build(skeleton)
    if not bp['symbols']:
        raise ValueError('结构不足以生成图形谱。')
    units, meta = grammar.classify_units(bp['paths'], bp['source_width'], bp['source_height'])
    art = studio.art_symbols(bp)
    source_hash = hashlib.sha256((folder / 'structural.png').read_bytes()).hexdigest()
    # Keep the legacy sample key inside this private manifest only. It refers
    # exclusively to this upload, not to the shared sample5 assets.
    slug = 'sample5'
    payload = dict(id=slug, name='我的图片 · 结构作品', exclusions=[], width=bp['source_width'],
                   height=bp['source_height'], art=art, contours=bp['paths'], dense_count=len(bp['symbols']),
                   drawn_count=len(art), source_hash=source_hash, units=studio.compact_units(units),
                   unit_meta=meta, voice_catalog=grammar.VOICE_CATALOG,
                   intake_job=folder.name, engine_hashes=hashes)
    notes = composer.compose_blueprint(bp, studio.BLUEPRINT_VARIANT, total_seconds=13)
    audible = [n for v in range(5) for n in renderer._thin_voice([n for n in notes if n['voice'] == v], 40)]
    ids = {n['id'] for n in audible}
    by_id = {n['id']: n for n in notes}
    for symbol in art:
        note = by_id[symbol['id']]
        symbol.update(raw_pitch=symbol['pitch'], pitch=note['pitch'], duration=note['duration'], audible=symbol['id'] in ids)
    pool = renderer._SoundFontPool.get(sf, rate=22050, gain=1.2)
    try:
        renderer.render_blueprint_soundfont(notes, assets / f'{slug}-blueprint.wav', sf_path=sf, total_seconds=13, rate=22050, gain=1.2, pool=pool)
        studio.export_midi(audible, assets / f'{slug}-blueprint.mid')
        instruments = composer._instrument_names(studio.BLUEPRINT_VARIANT)
        programs = composer._programs(studio.BLUEPRINT_VARIANT)
        payload['blueprint'] = dict(audio=f'studio/{slug}-blueprint.wav', variant=studio.BLUEPRINT_VARIANT,
            duration=13, notes=len(audible), candidate_notes=len(notes), symbols=len(bp['symbols']), drawn=len(art),
            voices=[dict(voice=v, label=studio.BP_BAND_LABELS[v], instrument=instruments[v], program=programs[v],
                         color=studio.BP_BAND_COLORS[v], notes=sum(n['voice'] == v for n in audible)) for v in range(5)])
        payload['soul'] = grammar.compose_units(units, 'soul', soul_style)
        from progressive_arrangement import arrange, PRESETS
        from color_dna import analyze
        color_dna = analyze(folder / 'original.png','uploaded original photograph') if (folder / 'original.png').exists() else None
        payload['color_dna'] = color_dna
        payload['progressive_engine_hashes'] = {name:hashes[name] for name in ('color_dna.py','progressive_arrangement.py','progressive_features.py')}
        strengths = ['off','soft','mid','auto','vivid'] if color_dna and color_dna['available'] else ['auto']
        # H2: the *arrangements* are cheap (about 5 ms each), so all of
        # them are still computed up front and stored in the manifest — the
        # studio UI needs the note lists for the visualisation and the
        # note inspector.  Only the *audio* is rendered on demand.
        payload['progressive_colors'] = {preset:{strength:arrange(payload['soul'],preset,units=units,color_dna=color_dna,color_strength=strength) for strength in strengths} for preset in PRESETS}
        payload['progressive_presets'] = {preset:versions['auto'] for preset,versions in payload['progressive_colors'].items()}
        payload['progressive'] = payload['progressive_presets']['nature']
        payload['soul_demo'] = make_demo_cut(payload['soul'])
        # The classified geometry is needed to re-arrange a variant on
        # demand.  It is removed again before the manifest is written.
        payload['units_source'] = units
        # H2: which Progressive audio has actually been rendered.  The
        # studio UI asks the server for the missing ones.
        payload['rendered_variants'] = []
        tracks = [('soul', 'soul', payload['soul']), ('soul_demo', 'soul-demo', payload['soul_demo'])]
        # H2: only the default Progressive combination is rendered now.
        # Every other combination is rendered on demand through
        # `/api/jobs/<id>/progressive?preset=&strength=` (see
        # `on_demand_render.py`).
        default_preset = on_demand.DEFAULT_PRESET
        default_strength = on_demand.DEFAULT_STRENGTH
        default_music = payload['progressive_colors'][default_preset][default_strength]
        tracks.append(('progressive', on_demand.variant_prefix(default_preset, default_strength), default_music))
        for key, prefix, music in tracks:
            for v in range(5):
                renderer.render_wav([n for n in music['notes'] if n['voice'] == v], assets / f'{slug}-{prefix}-{v}.wav',
                    sf_path=sf, total_seconds=music['duration'] + 1, rate=22050, pool=pool, normalize=key!='progressive')
            studio.export_midi(music['notes'], assets / f'{slug}-{prefix}.mid', music.get('tempo', 120), music.get('spatial_pan'))
            if key == 'progressive':
                from build_progressive_arrangement import mix_stems
                mix_stems(f'{slug}-{prefix}', music, assets)
                payload['rendered_variants'] = [[default_preset, default_strength]]
            if key != 'progressive':
                studio.export_spatial_mix(f'{slug}-{prefix}', music)
        if color_dna and color_dna['available']:
            from living_color import build as build_living_color
            build_living_color(payload,units,folder/'original.png',assets,pool,sf)
    finally:
        pool.close()
    # `units_source` is only needed while the workspace is being built; it
    # must not end up in the manifest (it is large and not part of the
    # public contract).
    payload.pop('units_source', None)
    for name, content in ENGINE.content.items():
        file = Path(name)
        if file.parent == Path('ui') and file.suffix in ('.html', '.css', '.js'):
            (workspace / file.name).write_bytes(content)
    html_path = workspace / 'studio.html'
    html_path.write_text(html_path.read_text(encoding='utf-8').replace('href="lab-v3.html"', 'href="/experience"').replace('实验记录 ↗', '上传新图片 ↗'), encoding='utf-8')
    # Source image and geometry share the same coordinate system. Artistic
    # output stays in intake until there is a verified alignment transform.
    Image.open(folder / 'structural.png').convert('RGB').save(workspace / f'{slug}.jpg')
    # Preserve the uploaded colour original so the Progressive reveal can
    # crossfade back to the real photo — no synthetic colourisation needed.
    original = folder / 'original.png'
    if original.exists():
        Image.open(original).convert('RGB').save(assets / f'{slug}-original.jpg', quality=90)
        payload['original_photo'] = dict(url=f'studio/{slug}-original.jpg',
            relationship='uploaded_original', alignment='uploaded_source',
            reveal_start=33., reveal_end=34.)
    (assets / f'{slug}.json').write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    (assets / 'manifest.json').write_text(json.dumps([dict(id=slug, name=payload['name'])], ensure_ascii=False), encoding='utf-8')
    from check_workspace import check
    check(folder)
    (folder / 'engine-version.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')


if __name__ == '__main__':
    # M8: the harmony style is selectable (`east` / `west`).  It is passed
    # on the command line so that the intake server can choose it through
    # `config.local.json` without changing the engine.
    build(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else 'east')
