"""Differential + invariant tests for the sliding-window scheduler.

`studio_grammar._schedule` replaced an O(n^2) heap-scanning scheduler with a
sliding-window implementation (see the "Performance (M3)" section of its
docstring).  The docstring promises the produced schedule is *identical* to
the old one; this module pins that promise down by keeping the original
algorithm here as a reference oracle and comparing the two on randomised
inputs.

The oracle is deliberately the slow implementation: it is only ever run on
small inputs so the suite stays fast.
"""
import heapq
import random
import sys
import time
import unittest
from pathlib import Path

# Resolve imports relative to this file so the suite runs from any cwd.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import studio_grammar as sg  # noqa: E402


def old_schedule(candidates, limit_end, max_concurrent=sg.MAX_CONCURRENT):
    """The original O(n^2) scheduler, kept as the reference oracle.

    Every accepted note stayed in a heap and the whole heap was rescanned
    for every candidate, which made dense blueprints quadratic.
    """
    heap = []
    accepted = []
    for c in candidates:
        s = float(c['start'])
        while heap and heap[0][0] <= s + 1e-9:
            heapq.heappop(heap)
        t = s
        dur = float(c['duration'])
        v = int(c['voice'])
        p = int(c['pitch'])
        for _ in range(4000):
            active = 0
            conflict = False
            earliest = None
            for e, st, vv, pp in heap:
                if st - 1e-9 <= t < e - 1e-9:
                    active += 1
                    if vv == v and pp == p:
                        conflict = True
                    if earliest is None or e < earliest:
                        earliest = e
            if active < max_concurrent and not conflict:
                break
            if earliest is None or earliest <= t + 1e-9:
                t += 0.05
            else:
                t = earliest
        if t + dur > limit_end - 0.05:
            continue
        c['start'] = round(t, 3)
        heapq.heappush(heap, (t + dur, t, v, p))
        accepted.append(c)
    return accepted


def make_candidates(n, seed=3, voices=5, pitches=(48, 50, 52, 55, 57)):
    """Deterministic pseudo-random candidate list, sorted like the real one."""
    random.seed(seed)
    cands = []
    for i in range(n):
        cands.append(dict(start=round(random.uniform(0, 120), 3),
                          duration=round(random.uniform(0.05, 1.6), 3),
                          voice=random.randint(0, voices - 1),
                          pitch=random.choice(pitches),
                          unit=dict(id='u%05d' % i)))
    cands.sort(key=lambda c: (c['start'], c['voice'], c['unit']['id']))
    return cands


class SchedulerDifferentialTests(unittest.TestCase):
    """The new scheduler must reproduce the old one note-for-note."""

    def _assert_same(self, n, seed, **kw):
        cands = make_candidates(n, seed=seed, **kw)
        limit = 130.0
        old = old_schedule([dict(c) for c in cands], limit)
        new = sg._schedule([dict(c) for c in cands], limit)
        self.assertEqual(len(old), len(new),
                         f'n={n} seed={seed}: accepted {len(old)} != {len(new)}')
        for a, b in zip(old, new):
            self.assertEqual(a['start'], b['start'],
                             f'n={n} seed={seed}: start {a["start"]} != {b["start"]}')
            self.assertEqual(a['voice'], b['voice'])
            self.assertEqual(a['pitch'], b['pitch'])
            self.assertEqual(a['duration'], b['duration'])
        return new

    def test_matches_reference_scheduler(self):
        for n in (1, 2, 37, 200, 900):
            self._assert_same(n, seed=3)

    def test_matches_reference_scheduler_across_seeds(self):
        for seed in range(6):
            self._assert_same(400, seed=seed)

    def test_matches_reference_scheduler_for_degenerate_inputs(self):
        # All notes on one voice+pitch: every note has to wait for the
        # previous one to release, exercising the clash path.
        self._assert_same(120, seed=1, voices=1, pitches=(60,))
        # Many voices, one pitch: exercises the polyphony cap path.
        self._assert_same(120, seed=2, voices=5, pitches=(60,))
        # One voice, many pitches: exercises the release-and-reuse path.
        self._assert_same(120, seed=3, voices=1, pitches=tuple(range(48, 72)))

    def test_respects_polyphony_cap(self):
        for n in (500, 2000):
            new = self._assert_same(n, seed=3)
            self.assertLessEqual(sg.overlap_peak(new), sg.MAX_CONCURRENT)

    def test_same_voice_pitch_never_sounds_twice(self):
        new = self._assert_same(600, seed=4)
        seen = {}
        for n in new:
            key = (n['voice'], n['pitch'])
            prev = seen.get(key)
            if prev is not None:
                self.assertLessEqual(prev['start'] + prev['duration'], n['start'] + 1e-9)
            seen[key] = n


class SchedulerEdgeCaseTests(unittest.TestCase):
    def test_empty_input(self):
        self.assertEqual(sg._schedule([], 30.0), [])

    def test_everything_rejected_when_limit_is_tight(self):
        cands = [dict(start=0.0, duration=1.0, voice=0, pitch=60,
                      unit=dict(id='a'))]
        self.assertEqual(sg._schedule(cands, 0.5), [])

    def test_single_note_is_kept(self):
        cands = [dict(start=1.0, duration=0.5, voice=0, pitch=60,
                      unit=dict(id='a'))]
        out = sg._schedule(cands, 30.0)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['start'], 1.0)

    def test_notes_are_not_pushed_past_the_limit(self):
        cands = make_candidates(400, seed=9)
        out = sg._schedule(cands, 40.0)
        for n in out:
            self.assertLessEqual(n['start'] + n['duration'], 40.0 - 0.05 + 1e-9)

    def test_custom_concurrency_cap_is_honoured(self):
        cands = make_candidates(400, seed=5)
        out = sg._schedule([dict(c) for c in cands], 130.0, max_concurrent=3)
        self.assertLessEqual(sg.overlap_peak(out), 3)


class SchedulerPerformanceTests(unittest.TestCase):
    def test_dense_input_does_not_regress_to_quadratic(self):
        """A quadratic regression would take ~170 s here; the sliding
        window takes ~12 s, so a generous 30 s ceiling still catches it."""
        cands = make_candidates(12000, seed=3)
        t0 = time.perf_counter()
        out = sg._schedule([dict(c) for c in cands], 130.0)
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 30.0,
                        f'scheduler took {elapsed:.1f}s on 12000 candidates')
        self.assertLessEqual(sg.overlap_peak(out), sg.MAX_CONCURRENT)


if __name__ == '__main__':
    unittest.main()
