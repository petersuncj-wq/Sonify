"""Regenerate CORE_MANIFEST.json from the files currently in the tree.

The manifest is the integrity file documented in ASSETS.md: it maps every
core file to its SHA256 digest.  It had drifted out of date (140 of 265
entries no longer matched, and 5 entries pointed at files that had moved
to photo/experiment/_archive/).

This script rebuilds it from the files that are actually tracked by git,
excluding generated artefacts and the manifest itself.

Usage::

    python tools/build_manifest.py          # write CORE_MANIFEST.json
    python tools/build_manifest.py --check  # verify without writing
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / 'CORE_MANIFEST.json'

# Files that are part of the release but are not tracked by git (the
# manifest covers them too), plus paths that should never be hashed.
SELF_EXCLUDE = {'CORE_MANIFEST.json'}


def git_tracked_files() -> list[str]:
    """Every file git tracks, as repo-relative POSIX paths."""
    out = subprocess.run(
        ['git', '-C', str(ROOT), 'ls-files', '-z'],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
    ).stdout
    return sorted(p for p in out.split('\0') if p)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for part in iter(lambda: f.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def build() -> dict[str, str]:
    manifest: dict[str, str] = {}
    for rel in git_tracked_files():
        if rel in SELF_EXCLUDE:
            continue
        p = ROOT / rel
        if not p.is_file():
            continue
        manifest[rel] = sha256(p)
    return manifest


def main() -> int:
    check_only = '--check' in sys.argv
    manifest = build()

    if not manifest:
        print('ERROR: no tracked files found', file=sys.stderr)
        return 2

    if check_only:
        current = json.loads(MANIFEST.read_text(encoding='utf-8')) if MANIFEST.is_file() else {}
        added = sorted(set(manifest) - set(current))
        removed = sorted(set(current) - set(manifest))
        changed = sorted(k for k in set(manifest) & set(current)
                         if manifest[k] != current[k])
        print(f'tracked files: {len(manifest)}  manifest entries: {len(current)}')
        print(f'added: {len(added)}  removed: {len(removed)}  changed: {len(changed)}')
        for label, items in (('added', added), ('removed', removed), ('changed', changed)):
            for item in items:
                print(f'  {label}: {item}')
        return 1 if (added or removed or changed) else 0

    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
        encoding='utf-8')
    print(f'Wrote {MANIFEST.name} with {len(manifest)} entries')
    return 0


if __name__ == '__main__':
    sys.exit(main())
