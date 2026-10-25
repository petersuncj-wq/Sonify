"""Offline SoundFont rendering via tinysoundfont.

Renders Soul Symphony and Progressive Revelation stems and the Blueprint
Display scan using FluidR3Mono_GM.sf3. Blueprint limits concurrent notes
per voice before rendering; the complete source-derived symbol field stays
visible in the graphic score.

Usage
-----
    from render_soundfont import render_wav
    render_wav(notes, OUT / 'sample0-v2-all.wav', sf_path=SOUNDFONT)
"""
from __future__ import annotations
import os
import wave
from pathlib import Path
from typing import Sequence

import numpy as np

try:
    import tinysoundfont as tsf
    HAVE_TSF = True
except Exception:
    HAVE_TSF = False


def find_soundfont(explicit: str | None = None,
                   search_dirs: list[Path] | None = None) -> str | None:
    """Locate a FluidR3_GM (.sf2 / .sf3) soundfont.

    Search order: explicit path → env vars → given dirs → vendor paths.
    Every path is resolved relative to this file, so the lookup does not
    depend on the current working directory.
    """
    for candidate in _soundfont_candidates(explicit, search_dirs):
        if candidate.exists():
            return str(candidate)
    # Also try any *.sf2 / *.sf3 inside the well-known soundfont folders.
    here = Path(__file__).resolve().parent
    root = here.parent.parent
    for folder in (here / 'dist' / 'soundfonts', root / 'soundfonts'):
        if folder.is_dir():
            for found in sorted(folder.iterdir()):
                if found.suffix.lower() in ('.sf2', '.sf3'):
                    return str(found)
    return None


def _soundfont_candidates(explicit: str | None = None,
                          search_dirs: list[Path] | None = None) -> list[Path]:
    """Every absolute path the soundfont lookup inspects."""
    here = Path(__file__).resolve().parent
    root = here.parent.parent
    paths: list[Path] = []
    if explicit:
        paths.append(Path(explicit))
    for env in ("PYIANNIX_SF2", "SONIFY_SF2", "SONIFY_SOUNDFONT"):
        value = os.environ.get(env)
        if value:
            paths.append(Path(value))
    if search_dirs:
        paths.extend(Path(d) for d in search_dirs)
    paths.extend([
        here / 'dist' / 'soundfonts' / 'FluidR3Mono_GM.sf3',
        here / 'dist' / 'soundfonts' / 'FluidR3_GM.sf2',
        here / 'dist' / 'soundfonts' / 'FluidR3_GM.sf3',
        root / 'photo' / 'experiment' / 'dist' / 'soundfonts' / 'FluidR3Mono_GM.sf3',
        root / 'soundfonts' / 'FluidR3Mono_GM.sf3',
        root / 'soundfonts' / 'FluidR3_GM.sf2',
    ])
    return paths


def searched_soundfont_paths(explicit: str | None = None) -> list[Path]:
    """Public helper: the absolute paths `find_soundfont()` inspects."""
    return _soundfont_candidates(explicit)


def _soundfont_missing_message() -> str:
    """Actionable error text listing every searched absolute path."""
    searched = _soundfont_candidates()
    return ('no FluidR3 .sf2 / .sf3 found; set the SONIFY_SF2 environment '
            'variable or place a soundfont in one of these locations:\n  '
            + '\n  '.join(str(p) for p in searched))


# Per-preset channel volume calibration, copied from MusicPaint's
# sounds.py — FluidR3's piano/pad are much quieter than the flutes.
_PRESET_VOLUME = {
    0: 114, 4: 60, 10: 66, 11: 90, 12: 80, 14: 70, 40: 80, 41: 80,
    42: 90, 48: 66, 49: 70, 52: 64, 58: 90, 61: 100, 65: 90, 66: 90,
    73: 72, 74: 70, 75: 70, 77: 54, 79: 64, 80: 64, 88: 80, 89: 90,
    96: 80, 105: 90, 106: 90, 107: 60, 108: 70, 116: 72,
}


def _voice_budget(notes: Sequence[dict]) -> int:
    """Max simultaneous note count (polyphony budget)."""
    events = []
    for n in notes:
        events.append((float(n['start']), 1))
        events.append((float(n['start']) + float(n['duration']), -1))
    events.sort(key=lambda e: (e[0], -e[1]))
    cur = maxc = 0
    for _, d in events:
        cur += d
        if cur > maxc:
            maxc = cur
    return maxc


def validate_note(note: dict) -> None:
    """M5 (robustness): reject notes that the MIDI spec cannot express.

    The renderer used to clamp silently:

        pitch = max(0, min(127, int(n['pitch'])))

    A note whose pitch fell outside MIDI 0–127 was therefore rendered at
    the edge of the keyboard without any warning.  That breaks the
    project's core promise that every note can be traced back to the
    geometry it came from: the *heard* pitch no longer matches the
    *computed* pitch, and nothing in the output says so.

    This validator raises instead.  It is called from every render entry
    point, so an out-of-range pitch fails loudly at the point where it can
    still be attributed to a source.  The clamp stays in place as a last
    line of defence for third-party callers that bypass the validator.
    """
    pitch = note.get('pitch')
    if pitch is None:
        raise ValueError(f"note {note.get('id', '?')} has no pitch")
    try:
        value = int(pitch)
    except (TypeError, ValueError):
        raise ValueError(
            f"note {note.get('id', '?')} has a non-numeric pitch {pitch!r}"
        ) from None
    if not 0 <= value <= 127:
        raise ValueError(
            f"note {note.get('id', '?')} pitch {value} is outside the MIDI "
            f"range 0–127 (source={note.get('source')!r}, voice={note.get('voice')!r})"
        )
    velocity = note.get('velocity')
    if velocity is not None:
        try:
            vel = int(velocity)
        except (TypeError, ValueError):
            raise ValueError(
                f"note {note.get('id', '?')} has a non-numeric velocity {velocity!r}"
            ) from None
        if not 0 <= vel <= 127:
            raise ValueError(
                f"note {note.get('id', '?')} velocity {vel} is outside the "
                f"MIDI range 0–127 (source={note.get('source')!r})"
            )


def validate_notes(notes: Sequence[dict]) -> None:
    """Validate a whole note list (see `validate_note`)."""
    for note in notes:
        validate_note(note)


class _SoundFontPool:
    """Singleton pool: load the .sf3 once, reuse for many render calls.

    Loading FluidR3Mono_GM.sf3 (~22 MB) takes ~7 s on Windows; rendering
    itself is sub-second.  This class makes the load amortised across all
    60 Soul Symphony + Progressive Revelation WAVs.
    """
    _instance = None

    def __init__(self, sf_path: str, rate: int = 44100, gain: float = 1.2):
        self.path = sf_path
        self.rate = rate
        self.gain = gain
        self.tsf = tsf.Synth(gain=gain, samplerate=rate)
        self.sfid = self.tsf.sfload(Path(sf_path).read_bytes())
        self.prog_to_ch: dict = {}

    def channel_for(self, program: int) -> int:
        """Bind a GM program to a channel (one per program). Max 16 programs per render."""
        if program in self.prog_to_ch:
            return self.prog_to_ch[program]
        if len(self.prog_to_ch) >= 16:
            raise RuntimeError(f'超过16个program限制（当前已有{len(self.prog_to_ch)}个），无法分配program {program}')
        for ch in range(16):
            if ch not in self.prog_to_ch.values():
                self.prog_to_ch[program] = ch
                self.tsf.program_select(ch, self.sfid, 0, int(program))
                self.tsf.control_change(ch, 7, _PRESET_VOLUME.get(int(program), 100))
                return ch
        raise RuntimeError('无可用MIDI通道')

    def close(self):
        try:
            self.tsf.sfunload(self.sfid)
        except Exception:
            pass
        self.tsf = None

    @classmethod
    def get(cls, sf_path: str, rate: int = 44100, gain: float = 1.2):
        # 如果实例已关闭（tsf为None），重新创建而非返回失效实例
        if cls._instance is None or cls._instance.tsf is None or cls._instance.path != sf_path \
                or cls._instance.rate != rate or cls._instance.gain != gain:
            if cls._instance is not None and cls._instance.tsf is not None:
                cls._instance.close()
            cls._instance = cls(sf_path, rate=rate, gain=gain)
        return cls._instance


def render_wav(notes: Sequence[dict], path: Path,
               sf_path: str | None = None,
               total_seconds: float = 18.0,
               rate: int = 44100,
               gain: float = 1.2,
               pool: _SoundFontPool | None = None, normalize: bool = True) -> int:
    """Render notes through FluidR3_GM and write a stereo 16-bit WAV.

    Returns the polyphony budget actually used; raises RuntimeError
    if tinysoundfont or the soundfont is unavailable.
    """
    if not HAVE_TSF:
        raise RuntimeError("tinysoundfont not installed")
    sf = sf_path or find_soundfont()
    if not sf:
        raise RuntimeError(_soundfont_missing_message())
    if not notes:
        # emit a silent WAV so the file is always present
        silent = np.zeros(int(total_seconds * rate), dtype=np.float32)
        _write_wav(silent, rate, path, channels=1)
        return 0
    # Acquire the shared synth
    if pool is None:
        pool = _SoundFontPool.get(sf, rate=rate, gain=gain)
    synth = pool.tsf
    # The cached synthesizer is reused across stems. Release tails from the
    # previous render must not become a false early note in this stem.
    synth.sounds_off()
    # Reset channel assignments for each render to prevent channel reuse from prior renders
    pool.prog_to_ch = {}
    # Convert note schedule to (sample, kind, ch, pitch, vel) events.
    events: list[tuple[int, int, int, int, int]] = []   # (sample, kind, ch, p1, p2)
    for n in notes:
        p = int(n.get('program', 0))
        ch = pool.channel_for(p)
        # M5: fail loudly on an out-of-range pitch instead of silently
        # clamping it to the edge of the keyboard.
        validate_note(n)
        pitch = max(0, min(127, int(n['pitch'])))
        vel = max(1, min(127, int(n.get('velocity', 80))))
        on_sample = int(round(float(n['start']) * rate))
        off_sample = int(round((float(n['start']) + float(n['duration'])) * rate))
        events.append((max(0, on_sample), 1, ch, pitch, vel))
        events.append((max(0, off_sample), 0, ch, pitch, 0))
    # Stable sort: at the same sample, note-off fires before note-on so
    # a rapid retrigger of the same pitch doesn't get swallowed.
    events.sort(key=lambda e: (e[0], e[1]))
    end_seconds = max(float(n['start']) + float(n['duration']) for n in notes) + 0.5
    total_samples = int(max(total_seconds, end_seconds) * rate)
    out = np.zeros((total_samples, 2), dtype=np.float32)
    def apply_event(event):
        _, kind, ch, pitch, vel = event
        if kind == 1:
            synth.noteon(ch, pitch, vel)
        else:
            synth.noteoff(ch, pitch)
    _render_timed_events(synth, events, out, rate, apply_event)
    # Soft saturate to keep peak below clipping
    out = np.tanh(out * 0.9)
    # Light feedback-delay reverb tail
    out = _add_simple_reverb(out, rate)
    # Peak-normalise to -3 dBFS
    peak = float(np.max(np.abs(out)) + 1e-9)
    if normalize and peak > 1e-9:
        out = out * (0.7 / peak)
    _write_wav(out, rate, path, channels=2)
    return _voice_budget(notes)


def _add_simple_reverb(audio: np.ndarray, rate: int) -> np.ndarray:
    """Stereo Schroeder reverb (2 combs + 1 all-pass per channel)."""
    delays_ms = (37, 53, 71, 97)
    decays = (0.84, 0.83, 0.82, 0.80)
    wet = np.zeros_like(audio)
    for d_ms, g in zip(delays_ms, decays):
        d = int(d_ms * rate / 1000)
        if d <= 0 or d >= len(audio):
            continue
        wet[d:] += audio[:-d] * g * 0.5
    ap_delay = int(11 * rate / 1000)
    if 0 < ap_delay < len(wet):
        ap = np.zeros_like(wet)
        ap[ap_delay:] = wet[:-ap_delay]
        wet = 0.65 * wet + 0.35 * ap
    return 0.78 * audio + 0.30 * wet


def _write_wav(audio: np.ndarray, rate: int, path: Path, channels: int) -> None:
    pcm = (audio * 32767.0).astype('<i2').tobytes()
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(channels)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(pcm)


def _render_timed_events(synth, events, out: np.ndarray, rate: int,
                         apply_event) -> None:
    """Apply MIDI events at their exact sample, then render to the next event.

    The old one-second block loop applied all note-ons and note-offs before
    producing that second of audio. Short notes could disappear completely.
    One-second blocks remain the maximum gap between actual event times.
    """
    pos = ei = 0
    total = len(out)
    while pos < total:
        while ei < len(events) and events[ei][0] <= pos:
            apply_event(events[ei])
            ei += 1
        next_event = events[ei][0] if ei < len(events) else total
        end = min(total, pos + rate, next_event)
        if end <= pos:
            raise ValueError('MIDI events must be sorted by sample position')
        audio = np.frombuffer(synth.generate_simple(end - pos),
                              dtype=np.float32).reshape(-1, 2)
        out[pos:end] = audio
        pos = end


def render_blueprint_soundfont(notes: Sequence[dict], path: Path,
                                sf_path: str | None = None,
                                total_seconds: float = 13.5,
                                rate: int = 44100,
                                gain: float = 1.2,
                                max_per_voice: int = 40,
                                pool: "_SoundFontPool | None" = None) -> int:
    """Render Blueprint notes through FluidR3_GM, thinned so no voice
    ever has more than `max_per_voice` simultaneous notes.  This
    avoids tinysoundfont's voice-pool overflow on the 12 000-symbol
    Blueprint input where the long-duration roof voice can pile up
    150+ simultaneous notes.

    Each voice is rendered separately to its own stereo buffer
    (using a fresh Synth) so the per-voice budget is enforced; the
    buffers are summed and written as one stereo WAV.  Returns the
    maximum observed per-voice polyphony.
    """
    if not HAVE_TSF:
        raise RuntimeError("tinysoundfont not installed")
    sf = sf_path or find_soundfont()
    if not sf:
        raise RuntimeError(_soundfont_missing_message())
    if not notes:
        silent = np.zeros(int(total_seconds * rate), dtype=np.float32)
        _write_wav(silent, rate, path, channels=2)
        return 0
    # Group notes by voice (0..4)
    by_voice: dict = {0: [], 1: [], 2: [], 3: [], 4: []}
    for n in notes:
        v = int(n.get('voice', 0))
        if v in by_voice:
            by_voice[v].append(n)
    # Render each voice to its own stereo buffer (one Synth per voice
    # to keep the voice pool fresh), then sum.
    total_samples = int(total_seconds * rate)
    master = np.zeros((total_samples, 2), dtype=np.float32)
    voice_progs = {0: 89, 1: 49, 2: 11, 3: 12, 4: 73}  # reasonable defaults
    # Override with the actual programs from the first note of each voice.
    for v, ns in by_voice.items():
        if ns:
            voice_progs[v] = int(ns[0].get('program', voice_progs[v]))
    for v, ns in by_voice.items():
        if not ns:
            continue
        # Thin: cap concurrent notes by dropping newest at any overlap
        # (sustain notes are kept; ornament notes are dropped first).
        ns_thin = _thin_voice(ns, max_per_voice)
        # Render this voice with a FRESH synth (so the voice pool is
        # clean — Blueprint has 5 voices × 5 programs, and a single
        # shared synth would run out of voices for the dense roof
        # voice).  ~7s sfload per voice is amortised via the shared
        # pool if one is provided.
        if pool is not None:
            synth = pool.tsf
            sfid = pool.sfid
        else:
            synth = tsf.Synth(gain=gain, samplerate=rate)
            sfid = synth.sfload(Path(sf).read_bytes())
        synth.sounds_off()
        # Force channel 0 to use the right program for this voice.
        synth.program_select(0, sfid, 0, voice_progs[v])
        synth.control_change(0, 7, _PRESET_VOLUME.get(voice_progs[v], 100))
        events: list = []
        for n in ns_thin:
            on = int(round(float(n['start']) * rate))
            off = int(round((float(n['start']) + float(n['duration'])) * rate))
            # M5: reject an out-of-range pitch loudly rather than clamping.
            validate_note(n)
            pitch = max(0, min(127, int(n['pitch'])))
            vel = max(1, min(127, int(n.get('velocity', 80))))
            events.append((max(0, on), 1, pitch, vel))
            events.append((max(0, off), 0, pitch, 0))
        events.sort(key=lambda e: (e[0], e[1]))
        out_v = np.zeros((total_samples, 2), dtype=np.float32)
        def apply_voice_event(event):
            _, kind, pitch, vel = event
            if kind == 1:
                synth.noteon(0, pitch, vel)
            else:
                synth.noteoff(0, pitch)
        _render_timed_events(synth, events, out_v, rate, apply_voice_event)
        # After this voice, silence all its notes so the next voice
        # starts clean.  (For shared-pool mode, we must not sfunload.)
        if pool is None:
            synth.sfunload(sfid)
        else:
            synth.sounds_off()
        master += out_v
    # Soft saturate + reverb + normalise
    master = np.tanh(master * 0.5)
    master = _add_simple_reverb(master, rate)
    peak = float(np.max(np.abs(master)) + 1e-9)
    if peak > 1e-9:
        master = master * (0.7 / peak)
    _write_wav(master, rate, path, channels=2)
    return max_per_voice


def _thin_voice(notes: Sequence[dict], max_concurrent: int) -> list:
    """Drop notes so no more than `max_concurrent` overlap in time.
    Notes are kept in order of start time; later notes are dropped
    when adding a new one would exceed the budget."""
    # Sweep: build (time, delta) event list per note, but only
    # accept a note if its on-event wouldn't push concurrency > budget.
    events: list = []   # for the selected subset
    active_until: list = []   # sorted end times of currently-active notes
    accepted: list = []
    for n in sorted(notes, key=lambda x: (x['start'], -x.get('duration', 0))):
        # Drop notes whose end has already passed
        end = float(n['start']) + float(n['duration'])
        active_until = [t for t in active_until if t > float(n['start'])]
        if len(active_until) >= max_concurrent:
            continue   # drop this note
        active_until.append(end)
        active_until.sort()
        accepted.append(n)
    return accepted


# Smoke test
if __name__ == '__main__':
    print('tinysoundfont available:', HAVE_TSF)
    sf = find_soundfont()
    print('soundfont:', sf)
    # Play a 1-second C major scale through FluidR3
    notes = [
        dict(start=0.0,  duration=0.5, pitch=60, program=0,  velocity=90),  # C4 piano
        dict(start=0.5,  duration=0.5, pitch=62, program=0,  velocity=90),  # D
        dict(start=1.0,  duration=0.5, pitch=64, program=0,  velocity=90),  # E
        dict(start=1.5,  duration=0.5, pitch=65, program=0,  velocity=90),  # F
        dict(start=2.0,  duration=0.5, pitch=67, program=0,  velocity=90),  # G
    ]
    if sf and HAVE_TSF:
        out = Path('dist/_smoke_soundfont.wav')
        out.parent.mkdir(parents=True, exist_ok=True)
        n = render_wav(notes, out, sf_path=sf, total_seconds=3.0)
        print('rendered', n, 'note budget to', out, '(', out.stat().st_size, 'bytes )')
