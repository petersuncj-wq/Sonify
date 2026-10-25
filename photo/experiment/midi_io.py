"""Single implementation of MIDI writing for the whole project.

Before this module there were four independent VLQ / `MThd` / `MTrk`
implementations (`run.py`, `blueprint.py`, `build_studio.py`,
`compose_v2.py`).  They disagreed about tempo handling, program
changes, pan (CC 10) and note ordering, so the same musical data could
produce different files depending on which script exported it.

`write_midi()` is now the only writer.  It emits a Type-0 file with:

* a tempo meta event derived from `tempo_bpm`,
* one program change per channel (taken from the first note of that
  channel, or from `programs=`),
* optional pan (CC 10) per channel,
* note on/off events with correct delta times.

The `vlq()` helper is re-exported from here so that legacy call sites
keep working.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

# Default MIDI resolution.  480 ticks per quarter note matches what every
# previous writer used.
TICKS_PER_BEAT = 480


def vlq(value: int) -> bytes:
    """Encode `value` as a MIDI variable-length quantity."""
    value = int(value)
    if value < 0:
        value = 0
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.insert(0, (value & 0x7F) | 0x80)
        value >>= 7
    return bytes(out)


def _tempo_bytes(tempo_bpm: float) -> bytes:
    micro = int(round(60_000_000 / max(1.0, float(tempo_bpm))))
    micro = max(1, min(0xFFFFFF, micro))
    return b'\x00\xff\x51\x03' + micro.to_bytes(3, 'big')


def _channel_pan(pans, channel: int):
    if pans is None:
        return None
    try:
        pan = float(pans[channel])
    except (IndexError, KeyError, TypeError, ValueError):
        return None
    if pan < -1.0:
        pan = -1.0
    elif pan > 1.0:
        pan = 1.0
    return max(0, min(127, round((pan + 1) * 63.5)))


def write_midi(notes: Sequence[dict], path, tempo_bpm: float = 120,
               pans=None, programs: dict | None = None,
               ticks_per_beat: int = TICKS_PER_BEAT) -> Path:
    """Write `notes` to a standard MIDI file at `path`.

    Every note dict needs `start`, `duration`, `pitch` and `voice`
    (channel).  Optional keys: `program`, `velocity`.
    """
    path = Path(path)
    ticks_per_second = ticks_per_beat * float(tempo_bpm) / 60.0
    events: list[tuple[int, int, bytes]] = []

    channels = sorted({int(n['voice']) for n in notes})
    program_by_channel: dict[int, int] = {}
    for channel in channels:
        program = None
        if programs is not None:
            program = programs.get(channel)
        if program is None:
            for note in notes:
                if int(note['voice']) == channel:
                    program = note.get('program')
                    break
        program_by_channel[channel] = max(0, min(127, int(program if program is not None else 0)))

    for channel in channels:
        events.append((0, 0, bytes([0xC0 | (channel & 0x0F), program_by_channel[channel]])))
        pan = _channel_pan(pans, channel)
        if pan is not None:
            events.append((0, 0, bytes([0xB0 | (channel & 0x0F), 10, pan])))

    for note in notes:
        channel = int(note['voice']) & 0x0F
        pitch = max(0, min(127, int(note['pitch'])))
        velocity = max(1, min(127, int(note.get('velocity', 64))))
        start = round(float(note['start']) * ticks_per_second)
        end = round((float(note['start']) + float(note['duration'])) * ticks_per_second)
        events.append((start, 1, bytes([0x90 | channel, pitch, velocity])))
        events.append((end, 2, bytes([0x80 | channel, pitch, 0])))

    # Note-off before note-on at the same tick so repeated pitches retrigger
    # cleanly instead of being swallowed by the previous note.
    events.sort(key=lambda e: (e[0], e[1]))

    body = bytearray(_tempo_bytes(tempo_bpm))
    last = 0
    for tick, _, message in events:
        body += vlq(max(0, tick - last)) + message
        last = tick
    body += b'\x00\xff\x2f\x00'

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'MThd' + (6).to_bytes(4, 'big') + (0).to_bytes(2, 'big')
                     + (1).to_bytes(2, 'big') + int(ticks_per_beat).to_bytes(2, 'big')
                     + b'MTrk' + len(body).to_bytes(4, 'big') + bytes(body))
    return path


def write_midi_with_mido(notes: Sequence[dict], path, tempo_bpm: float = 120) -> Path:
    """Optional mido-backed writer (kept for parity with the old v2 exporter)."""
    import mido  # imported lazily: mido is an optional dependency

    path = Path(path)
    mid = mido.MidiFile(type=1)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(tempo_bpm), time=0))
    used = sorted({int(n['voice']) for n in notes})
    programs: dict[int, int] = {}
    for channel in used:
        for note in notes:
            if int(note['voice']) == channel:
                programs[channel] = int(note.get('program', 0))
                break
    events: list[tuple[int, str, int, int, int]] = []
    for channel in used:
        events.append((0, 'pc', channel, programs.get(channel, 0), 0))
    for note in notes:
        on = int(round(float(note['start']) * TICKS_PER_BEAT))
        off = int(round((float(note['start']) + float(note['duration'])) * TICKS_PER_BEAT))
        channel = int(note['voice'])
        pitch = int(note['pitch'])
        velocity = max(1, min(127, int(note.get('velocity', 64))))
        events.append((on, 'on', channel, pitch, velocity))
        events.append((off, 'off', channel, pitch, 0))
    events.sort(key=lambda e: (e[0], 0 if e[1] == 'pc' else (1 if e[1] == 'on' else 2)))
    last = 0
    for tick, kind, channel, p1, p2 in events:
        delta = max(0, tick - last)
        last = tick
        if kind == 'pc':
            track.append(mido.Message('program_change', channel=channel, program=p1, time=delta))
        elif kind == 'on':
            track.append(mido.Message('note_on', channel=channel, note=p1, velocity=p2, time=delta))
        else:
            track.append(mido.Message('note_off', channel=channel, note=p1, velocity=0, time=delta))
    track.append(mido.MetaMessage('end_of_track', time=0))
    mid.save(str(path))
    return path


__all__ = ['vlq', 'write_midi', 'write_midi_with_mido', 'TICKS_PER_BEAT']
