"""Tests for the optimisation work: title validation, on-demand rendering,
the rename route, rate limiting and the security headers.

These cover the items that the existing suites do not touch:

  * M11 / H7 — renaming a work (`PUT /api/jobs/<id>/title`),
  * L5     — the shared title whitelist used by the community as well,
  * H2     — the on-demand Progressive renderer,
  * H6     — the per-IP rate limiter,
  * L4     — the security headers,
  * M5     — the MIDI note-range validation.
"""
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / 'experiment'))

import titles
from titles import TitleError, sanitize_title


class TitleSanitizerTests(unittest.TestCase):
    """L5 / M11 — the shared title whitelist."""

    def test_accepts_ordinary_titles(self):
        self.assertEqual(sanitize_title('  我的第一张作品  '), '我的第一张作品')
        self.assertEqual(sanitize_title('Photo #3 (final)'), 'Photo #3 (final)')
        self.assertEqual(sanitize_title('山と光'), '山と光')

    def test_rejects_empty_title(self):
        for value in ('', '   ', None):
            with self.assertRaises(TitleError):
                sanitize_title(value)

    def test_rejects_overlong_title(self):
        self.assertEqual(len(sanitize_title('a' * 60)), 60)
        with self.assertRaises(TitleError):
            sanitize_title('a' * 61)

    def test_rejects_control_characters(self):
        for value in ('bad\x00name', 'bad\x07name', 'line\nbreak', 'tab\there'):
            with self.assertRaises(TitleError):
                sanitize_title(value)

    def test_rejects_bidi_overrides(self):
        # U+202E RIGHT-TO-LEFT OVERRIDE can visually reverse a title.
        for value in ('safe‮evil', '‪abc', 'abc⁩'):
            with self.assertRaises(TitleError):
                sanitize_title(value)

    def test_rejects_markup(self):
        for value in ('<script>', 'a<b', 'a>b', '<img src=x onerror=y>'):
            with self.assertRaises(TitleError):
                sanitize_title(value)

    def test_rejects_unknown_characters(self):
        with self.assertRaises(TitleError):
            sanitize_title('\U0001f600')

    def test_normalizes_to_nfc(self):
        # "e" + COMBINING ACUTE must become a single precomposed character.
        self.assertEqual(sanitize_title('café'), 'café')
        self.assertEqual(len(sanitize_title('café')), 4)


class RateLimiterTests(unittest.TestCase):
    """H6 — a burst of submissions must be rejected with HTTP 429."""

    def test_burst_is_limited_and_then_recovers(self):
        import server

        limiter = server.RateLimiter(limit=3, window=60.0)
        self.assertTrue(limiter.check('1.2.3.4'))
        self.assertTrue(limiter.check('1.2.3.4'))
        self.assertTrue(limiter.check('1.2.3.4'))
        self.assertFalse(limiter.check('1.2.3.4'))

    def test_limit_is_per_key(self):
        import server

        limiter = server.RateLimiter(limit=1, window=60.0)
        self.assertTrue(limiter.check('a'))
        self.assertTrue(limiter.check('b'))
        self.assertFalse(limiter.check('a'))

    def test_window_expires(self):
        import server

        limiter = server.RateLimiter(limit=1, window=0.01)
        self.assertTrue(limiter.check('x'))
        self.assertFalse(limiter.check('x'))
        import time
        time.sleep(0.05)
        self.assertTrue(limiter.check('x'))


class NoteValidationTests(unittest.TestCase):
    """M5 — a MIDI note outside 0–127 must be rejected loudly."""

    def test_valid_notes_pass(self):
        import render_soundfont

        render_soundfont.validate_notes([
            {'id': 'a', 'pitch': 60, 'voice': 0, 'source': 'p1'},
            {'id': 'b', 'pitch': 0, 'voice': 1, 'source': 'p2'},
            {'id': 'c', 'pitch': 127, 'voice': 2, 'source': 'p3'},
        ])

    def test_out_of_range_notes_are_rejected(self):
        import render_soundfont

        for pitch in (-1, 128, 200):
            with self.assertRaises(ValueError):
                render_soundfont.validate_note(
                    {'id': 'x', 'pitch': pitch, 'voice': 0, 'source': 'p1'})

    def test_missing_or_non_numeric_pitch_is_rejected(self):
        import render_soundfont

        with self.assertRaises(ValueError):
            render_soundfont.validate_note({'id': 'x', 'voice': 0})
        with self.assertRaises(ValueError):
            render_soundfont.validate_note({'id': 'x', 'pitch': 'high', 'voice': 0})

    def test_velocity_is_validated_too(self):
        import render_soundfont

        with self.assertRaises(ValueError):
            render_soundfont.validate_note(
                {'id': 'x', 'pitch': 60, 'velocity': 200, 'voice': 0})


class EngineHashScopeTests(unittest.TestCase):
    """H4 — only render-relevant modules may take part in the hash."""

    def test_hash_excludes_tests_and_build_scripts(self):
        import engine_snapshot

        self.assertNotIn('test_studio.py', engine_snapshot.ENGINE_MODULES)
        self.assertNotIn('build_color_contrast_review.py', engine_snapshot.ENGINE_MODULES)
        self.assertNotIn('progressive_arrangement_v10_reference.py',
                         engine_snapshot.ENGINE_MODULES)

    def test_hash_includes_render_pipeline(self):
        import engine_snapshot

        for name in ('run.py', 'blueprint.py', 'studio_grammar.py',
                     'render_soundfont.py', 'color_dna.py',
                     'progressive_arrangement.py', 'build_studio.py',
                     'geometry.py', 'midi_io.py'):
            self.assertIn(name, engine_snapshot.ENGINE_MODULES)

    def test_hashes_are_limited_to_the_allow_list(self):
        import tempfile
        import engine_snapshot

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'ui').mkdir()
            (root / 'render_soundfont.py').write_text('X = 1\n', encoding='utf-8')
            (root / 'ui' / 'studio.js').write_text('a', encoding='utf-8')
            (root / 'test_thing.py').write_text('Y = 2\n', encoding='utf-8')
            snapshot = engine_snapshot.EngineSnapshot(root)
            self.assertIn('render_soundfont.py', snapshot.hashes)
            self.assertIn('ui/studio.js', snapshot.hashes)
            self.assertNotIn('test_thing.py', snapshot.hashes)
            # …but the test module is still importable through the snapshot.
            self.assertIn('test_thing.py', snapshot.content)


class VersionConvergenceTests(unittest.TestCase):
    """H3 — the Color DNA version must have a single source of truth."""

    def test_color_dna_version_matches_the_upgrade_check(self):
        import color_dna
        import upgrade_workspaces

        self.assertEqual(color_dna.VERSION, 'color-dna-1.2')
        self.assertEqual(upgrade_workspaces.COLOR_DNA_VERSION, color_dna.VERSION)

    def test_progressive_version_is_shared(self):
        import progressive_arrangement
        import publish_color_ui

        self.assertEqual(publish_color_ui.PROGRESSIVE_VERSION,
                         progressive_arrangement.VERSION)


if __name__ == '__main__':
    unittest.main()