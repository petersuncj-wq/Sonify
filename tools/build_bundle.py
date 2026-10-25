"""Build the downloadable "runnable" bundle from the repository source.

The repository deliberately does not commit the runtime assets (soundfont,
portable vendor wheels, the built Paint pages, the scroll paintings): they
total ~7.9 GB.  Those assets only exist inside the published Release zip.

A new bundle is therefore built in two steps:

1. Extract the previous release bundle, which carries every runtime asset
   byte for byte.
2. Overlay the repository's current tracked files on top of it, so the
   bundle's *code* always matches the current ``main``.

No runtime asset is ever regenerated, and no tracked file is lost -- the
result is the newest source wrapped around the known-good assets.

Usage::

    python tools/build_bundle.py --base Sonify-Runnable-20261018.zip \\
        --out Sonify-Runnable-20261025.zip [--name Sonify-Runnable-20261025]

    # add --date to derive the bundle name and build date from today
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def git(*args: str) -> str:
    r = subprocess.run(['git', '-C', str(ROOT)] + list(args),
                       capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    return r.stdout.strip()


def git_tracked_files() -> list[str]:
    out = git('ls-files', '-z')
    return sorted(p for p in out.split('\0') if p)


def extract_base(base_zip: Path, work: Path) -> Path:
    """Extract the base bundle and return the directory holding its files."""
    with zipfile.ZipFile(base_zip) as z:
        z.extractall(work)
    roots = [p for p in work.iterdir() if p.is_dir()]
    if len(roots) != 1:
        raise SystemExit(f'ERROR: unexpected bundle layout: {roots}')
    return roots[0]


def overlay_source(bundle: Path) -> tuple[int, int]:
    """Copy the repository's tracked files over the extracted bundle."""
    overlaid = missing = 0
    for rel in git_tracked_files():
        src = ROOT / rel
        if not src.is_file():
            missing += 1
            continue
        dst = bundle / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_file() and sha256(dst) == sha256(src):
            continue
        shutil.copyfile(src, dst)
        overlaid += 1
    return overlaid, missing


def refresh_metadata(bundle: Path, name: str, built_at: str) -> None:
    info_path = bundle / 'BUNDLE_INFO.json'
    if not info_path.is_file():
        return
    info = json.loads(info_path.read_text(encoding='utf-8-sig'))
    info['name'] = 'Sonify Runnable'
    info['version'] = '1.1'
    info['built_at'] = built_at
    info['repo'] = 'https://github.com/DClovewatch-deville/Sonify1.1'
    info['source_commit'] = git('rev-parse', 'HEAD')
    info_path.write_text(
        json.dumps(info, ensure_ascii=False, indent=4), encoding='utf-8')


def make_zip(bundle: Path, out_zip: Path) -> None:
    files = sorted(p for p in bundle.rglob('*') if p.is_file())
    if out_zip.exists():
        out_zip.unlink()
    with zipfile.ZipFile(out_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in files:
            z.write(p, arcname=str(p.relative_to(bundle.parent)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--base', required=True,
                    help='path to the previous release bundle (zip)')
    ap.add_argument('--out', required=True, help='output zip path')
    ap.add_argument('--name', default=None,
                    help='root folder name inside the zip '
                         '(default: Sonify-Runnable-<YYYYMMDD>)')
    ap.add_argument('--date', default=None,
                    help='build date as YYYYMMDD (default: today)')
    ap.add_argument('--work', default=None,
                    help='scratch directory (default: a temp dir)')
    args = ap.parse_args()

    base_zip = Path(args.base).resolve()
    out_zip = Path(args.out).resolve()
    if not base_zip.is_file():
        raise SystemExit(f'ERROR: base bundle not found: {base_zip}')

    stamp = args.date or date.today().strftime('%Y%m%d')
    name = args.name or f'Sonify-Runnable-{stamp}'

    work = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix='sonify-bundle-'))
    try:
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)

        bundle = extract_base(base_zip, work)
        print(f'base bundle   : {base_zip.name}')
        print(f'extracted to  : {bundle}')

        if bundle.name != name:
            bundle = bundle.rename(bundle.parent / name)
            print(f'renamed root  : {name}')

        overlaid, missing = overlay_source(bundle)
        print(f'files overlaid: {overlaid}')
        if missing:
            print(f'WARNING: {missing} tracked files were missing on disk')

        refresh_metadata(bundle, name, stamp)

        files = [p for p in bundle.rglob('*') if p.is_file()]
        total = sum(p.stat().st_size for p in files)
        print(f'bundle        : {len(files)} files, {total / 1048576:.1f} MB uncompressed')

        make_zip(bundle, out_zip)
        print(f'wrote         : {out_zip} ({out_zip.stat().st_size / 1048576:.1f} MB)')
        return 0
    finally:
        if not args.work and work.exists():
            shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
