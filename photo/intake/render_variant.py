"""Render one Progressive variant for an existing workspace (H2, on demand).

Run as a subprocess by the intake server:

    python render_variant.py <job-folder> <preset> <strength>

The workspace must already contain a finished `workspace/studio/sample5.json`
manifest (with `progressive_colors` and `units_source` reconstruction data).
The script renders the five voice stems, the spatial mix and the MIDI file
for the requested combination, then appends the combination to the
manifest's `rendered_variants` list.

The script is idempotent: if the files already exist it exits immediately.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXPERIMENT = ROOT.parent / 'experiment'
sys.path[:0] = [str(EXPERIMENT / 'vendor'), str(EXPERIMENT), str(ROOT)]

from engine_snapshot import EngineSnapshot
ENGINE = EngineSnapshot(EXPERIMENT).install()

import numpy as np
from PIL import Image

import blueprint
import build_studio as studio
import studio_grammar as grammar
import render_soundfont as renderer
import on_demand_render as on_demand


def main(folder: str, preset: str, strength: str) -> int:
    folder = Path(folder).resolve()
    assets = folder / 'workspace' / 'studio'
    manifest = assets / 'sample5.json'
    if not manifest.is_file():
        raise FileNotFoundError(f'no studio manifest in {folder}')
    payload = json.loads(manifest.read_text(encoding='utf-8'))

    if not on_demand.variant_available(payload, preset, strength):
        raise KeyError(f'no Progressive arrangement for preset={preset!r} strength={strength!r}')

    # The geometry is needed to re-arrange the variant.  It is derived
    # from the same structural image that produced the original build, so
    # the result is identical to what an up-front render would have
    # produced.
    units_source = payload.get('units_source')
    if units_source is None:
        structural = folder / 'structural.png'
        if not structural.is_file():
            raise FileNotFoundError(f'no structural.png in {folder}')
        skeleton = np.array(Image.open(folder / 'skeleton.png').convert('L'))
        bp = blueprint.build(skeleton)
        units, _ = grammar.classify_units(bp['paths'], bp['source_width'], bp['source_height'])
        units_source = units

    payload['units_source'] = units_source

    sf = renderer.find_soundfont()
    if not sf:
        raise RuntimeError('没有找到现有音乐渲染所需的 SoundFont。')

    studio.OUT, studio.ASSETS = folder / 'workspace', assets
    result = on_demand.render_variant(
        payload, assets, preset, strength,
        sf_path=sf, studio=studio, renderer=renderer)

    # Record the newly rendered combination in the manifest so that the
    # UI knows what it may play.
    rendered = [list(x) for x in payload.get('rendered_variants', [])]
    entry = [preset, strength]
    if entry not in rendered:
        rendered.append(entry)
    payload['rendered_variants'] = rendered

    payload.pop('units_source', None)
    pending = manifest.with_suffix('.json.tmp')
    pending.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    pending.replace(manifest)

    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    if len(sys.argv) < 4:
        print('usage: render_variant.py <folder> <preset> <strength>', file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2], sys.argv[3]))
