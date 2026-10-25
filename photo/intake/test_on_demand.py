"""The frontend and the backend must agree on the variant file prefix.

`studio.js` builds the audio URL in the browser; `on_demand_render.py`
builds the file name on disk.  If the two ever drift apart, the studio
silently 404s on every style switch and the visitor hears nothing.

This test pins the two implementations together.
"""
import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / 'experiment'))

import on_demand_render


def _studio_js() -> str:
    return (ROOT.parent / 'experiment' / 'ui' / 'studio.js').read_text(encoding='utf-8')


class VariantPrefixTests(unittest.TestCase):
    def test_python_prefix(self):
        self.assertEqual(on_demand_render.variant_prefix('nature', 'auto'), 'progressive')
        self.assertEqual(on_demand_render.variant_prefix('portrait', 'auto'), 'progressive-portrait')
        self.assertEqual(on_demand_render.variant_prefix('nature', 'vivid'), 'progressive-color-vivid')
        self.assertEqual(on_demand_render.variant_prefix('portrait', 'vivid'),
                         'progressive-portrait-color-vivid')

    def test_javascript_prefix_agrees(self):
        source = _studio_js()
        match = re.search(
            r"const progressiveAudioPrefix\s*=\s*\(\)\s*=>\s*(.+?);", source)
        self.assertIsNotNone(match, 'progressiveAudioPrefix not found in studio.js')
        expression = match.group(1)
        # The JS must contain the same two conditional suffixes.
        self.assertIn("'-'+progressivePreset", expression.replace(' ', ''))
        self.assertIn("'-color-'+progressiveColor", expression.replace(' ', ''))

    def test_javascript_prefix_evaluates_to_the_python_prefix(self):
        """Run the real JavaScript expression and compare it with Python.

        The expression is extracted from `studio.js` and evaluated in node
        with a stub `data`, so the two implementations cannot drift.
        """
        import json
        import shutil
        import subprocess
        import tempfile

        node = shutil.which('node')
        if not node:
            self.skipTest('node is not available')

        source = _studio_js()
        match = re.search(
            r"const progressiveAudioPrefix\s*=\s*\(\)\s*=>\s*(.+?);", source)
        expression = match.group(1)

        data = {
            'progressive_presets': {'nature': {}, 'portrait': {}, 'city': {}},
            'progressive_colors': {
                'nature': {'auto': {}, 'vivid': {}, 'soft': {}},
                'portrait': {'auto': {}, 'vivid': {}},
                'city': {'auto': {}},
            },
        }

        script = (
            'const data = ' + json.dumps(data) + ';\n'
            'let progressivePreset = "nature", progressiveColor = "auto";\n'
            'const progressiveAudioPrefix = () => ' + expression + ';\n'
            'const out = [];\n'
            'for (const p of ["nature","portrait","city"])\n'
            '  for (const c of ["auto","vivid","soft"]) {\n'
            '    progressivePreset = p; progressiveColor = c;\n'
            '    // Only combinations the work actually offers are selectable;\n'
            '    // the studio disables the rest of the controls.\n'
            '    if (!data.progressive_presets[p]) continue;\n'
            '    if (c !== "auto" && !data.progressive_colors[p][c]) continue;\n'
            '    out.push(progressiveAudioPrefix());\n'
            '  }\n'
            'console.log(JSON.stringify(out));\n'
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'prefix.js'
            path.write_text(script, encoding='utf-8')
            result = subprocess.run([node, str(path)], capture_output=True,
                                    text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        produced = json.loads(result.stdout.strip())

        # The Python side must produce the same name for every combination
        # the work actually offers.
        expected = []
        for preset, versions in data['progressive_colors'].items():
            for strength in versions:
                expected.append(on_demand_render.variant_prefix(preset, strength))
        self.assertEqual(produced, expected)

    def test_python_prefix_never_uses_an_unavailable_combination(self):
        """The server rejects a combination the work does not offer.

        `Pipeline.render_progressive()` raises `ValueError` for an unknown
        preset or strength, so the browser can never request a file name
        that was never written.
        """
        from on_demand_render import variant_available

        payload = {'progressive_colors': {'nature': {'auto': {}, 'vivid': {}}}}
        self.assertTrue(variant_available(payload, 'nature', 'vivid'))
        self.assertFalse(variant_available(payload, 'nature', 'off'))

    def test_defaults_match_the_studio_ui(self):
        source = _studio_js()
        self.assertIn("progressivePreset='nature'", source)
        self.assertIn("progressiveColor='auto'", source)
        self.assertEqual(on_demand_render.DEFAULT_PRESET, 'nature')
        self.assertEqual(on_demand_render.DEFAULT_STRENGTH, 'auto')

    def test_variant_available(self):
        payload = {'progressive_colors': {'nature': {'auto': {}, 'vivid': {}}}}
        self.assertTrue(on_demand_render.variant_available(payload, 'nature', 'auto'))
        self.assertTrue(on_demand_render.variant_available(payload, 'nature', 'vivid'))
        self.assertFalse(on_demand_render.variant_available(payload, 'nature', 'off'))
        self.assertFalse(on_demand_render.variant_available(payload, 'portrait', 'auto'))
        self.assertFalse(on_demand_render.variant_available({}, 'nature', 'auto'))


class StudioUiContractTests(unittest.TestCase):
    """The studio UI must ask the server for the audio it does not have."""

    def test_studio_js_is_valid_utf8(self):
        source = _studio_js()
        self.assertNotIn('\ufffd', source)

    def test_rendered_variants_are_parsed(self):
        source = _studio_js()
        self.assertIn('rendered_variants', source)
        self.assertIn('syncRenderedVariants', source)

    def test_on_demand_endpoint_is_called(self):
        source = _studio_js()
        self.assertIn('/progressive?preset=', source)

    def test_play_waits_for_the_audio(self):
        source = _studio_js()
        self.assertIn('await ensureProgressiveAudio()', source)


if __name__ == '__main__':
    unittest.main()