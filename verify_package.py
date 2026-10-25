"""Verify the release files against their recorded SHA256 digests.

The manifest shipped with this package is ``CORE_MANIFEST.json`` (see
``ASSETS.md``): it maps every core file to its SHA256 digest and is the
file the release instructions tell reviewers to check.

Usage::

    python verify_package.py

Exits non-zero if any listed file is missing or has changed.
"""
from pathlib import Path
import hashlib
import json
import sys

root = Path(__file__).resolve().parent
manifest_path = root / 'CORE_MANIFEST.json'

if not manifest_path.is_file():
    print(f'ERROR: manifest not found: {manifest_path}', file=sys.stderr)
    sys.exit(2)

expected = json.loads(manifest_path.read_text(encoding='utf8'))

failures = []
for name, digest in expected.items():
    p = root / name
    if not p.is_file():
        failures.append((name, 'missing'))
        continue
    h = hashlib.sha256()
    with p.open('rb') as f:
        for part in iter(lambda: f.read(1024 * 1024), b''):
            h.update(part)
    if h.hexdigest() != digest:
        failures.append((name, 'changed'))

print(f'Verified {len(expected)} files. Failures: {len(failures)}')
for item in failures:
    print(*item)
sys.exit(bool(failures))
