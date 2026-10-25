"""On-demand rendering of one Progressive variant (H2).

**Why this module exists**

`bridge.py` used to render *every* Progressive combination up front:

    4 presets x 5 colour strengths = 20 arrangements
    x 5 voice stems + 1 mix      = 120 WAV files
    plus Soul / Soul demo / Living Color      ~= 190 WAV files

Every one of those WAVs is a 37-second stereo file, so a single upload
produced roughly 300 MB of audio and spent the bulk of the 900-second
music budget on combinations that nobody ever listens to.  The user
typically plays one or two.

**What this module does**

`render_variant()` renders exactly **one** (preset, strength) pair: the
five voice stems, the spatial mix and the MIDI file.  It is called

  * once during the initial build, for the default combination
    (`nature` / `auto`), and
  * on demand, when the visitor switches to another combination in the
    studio UI.

The arrangement itself (`arrange()`) is cheap — 5 ms per combination —
so it is recomputed rather than cached; only the audio rendering is
expensive and therefore only done when needed.

**Idempotence**

`render_variant()` is safe to call repeatedly: if the target files
already exist and are newer than the payload, it returns immediately.
This makes it safe to retry after a failed request.
"""
from __future__ import annotations

from pathlib import Path

# The default combination that is always rendered up front.  It matches
# the studio UI's initial selection (`nature` / `auto`).
DEFAULT_PRESET = 'nature'
DEFAULT_STRENGTH = 'auto'


def variant_prefix(preset: str, strength: str) -> str:
    """The file-name prefix of one Progressive variant.

    Must stay in sync with `studio.js`:

        progressiveAudioPrefix = () => 'progressive'
            + (preset !== 'nature' ? '-' + preset : '')
            + (strength !== 'auto' ? '-color-' + strength : '');
    """
    return ('progressive'
            + ('' if preset == 'nature' else '-' + preset)
            + ('' if strength == 'auto' else '-color-' + strength))


def variant_available(payload: dict, preset: str, strength: str) -> bool:
    """True when the payload can produce this variant at all."""
    colors = payload.get('progressive_colors') or {}
    versions = colors.get(preset)
    return bool(versions) and strength in versions


def render_variant(payload: dict, assets: Path, preset: str, strength: str,
                   pool=None, sf_path: str | None = None,
                   studio=None, renderer=None) -> dict:
    """Render one Progressive variant and return its description.

    `payload` is the studio manifest; it is *not* modified.
    Returns a dict with the prefix and the paths that were written.
    """
    from progressive_arrangement import arrange
    from build_progressive_arrangement import mix_stems
    import build_studio as studio_module
    import render_soundfont as renderer_module

    studio = studio or studio_module
    renderer = renderer or renderer_module

    assets = Path(assets)
    slug = payload['id']
    prefix = variant_prefix(preset, strength)
    stems = [assets / f'{slug}-{prefix}-{v}.wav' for v in range(5)]
    mix = assets / f'{slug}-{prefix}-mix.wav'
    midi = assets / f'{slug}-{prefix}.mid'

    # Already rendered?  Nothing to do.
    if mix.is_file() and midi.is_file() and all(p.is_file() for p in stems):
        return dict(prefix=prefix, preset=preset, strength=strength,
                    cached=True, stems=[p.name for p in stems],
                    mix=mix.name, midi=midi.name)

    versions = (payload.get('progressive_colors') or {}).get(preset) or {}
    if strength not in versions:
        raise KeyError(f'no Progressive arrangement for preset={preset!r} strength={strength!r}')

    # The arrangement itself is cheap; recompute it so that a variant can
    # be rendered long after the initial build.
    music = arrange(payload['soul'], preset, units=payload.get('units_source'),
                    color_dna=payload.get('color_dna'),
                    color_strength=strength)

    owns_pool = pool is None
    if pool is None:
        sf = sf_path or renderer.find_soundfont()
        if not sf:
            raise RuntimeError('没有找到现有音乐渲染所需的 SoundFont。')
        pool = renderer._SoundFontPool.get(sf, rate=22050, gain=1.2)
    try:
        for v in range(5):
            renderer.render_wav([n for n in music['notes'] if n['voice'] == v],
                                stems[v], sf_path=sf_path, total_seconds=music['duration'] + 1,
                                rate=22050, pool=pool, normalize=False)
        studio.export_midi(music['notes'], midi, music.get('tempo', 120), music.get('spatial_pan'))
        mix_stems(f'{slug}-{prefix}', music, assets)
    finally:
        if owns_pool:
            pool.close()

    return dict(prefix=prefix, preset=preset, strength=strength,
                cached=False, stems=[p.name for p in stems],
                mix=mix.name, midi=midi.name)


__all__ = ['DEFAULT_PRESET', 'DEFAULT_STRENGTH', 'render_variant',
           'variant_available', 'variant_prefix']
