"""Import Photo modules from immutable source bytes, preserving original asset paths."""
import hashlib
import importlib.abc
import importlib.util
import sys
from pathlib import Path

# H4 (correctness): the snapshot used to hash *every* `*.py` file in the
# experiment folder plus everything under `ui/`.  That collection included
#
#   * five archived reference snapshots (`*_reference.py`),
#   * the test suites (`test_*.py`),
#   * one-off build / publish / review scripts.
#
# `upgrade_workspaces.py` compares these hashes against the recorded
# `engine-version.json` to decide whether a workspace has to be rebuilt,
# so editing *any* test file or *any* archived snapshot invalidated
# **every** existing work and triggered a full rebuild — and a full
# rebuild renders ~190 WAV files (H2).
#
# The collection is now an explicit allow-list of the modules and UI
# assets that actually take part in rendering.  Anything not listed here
# cannot influence the rendered output and therefore must not invalidate
# a workspace.
ENGINE_MODULES = (
    # Geometry extraction and blueprint building.
    'run.py',
    'blueprint.py',
    'studio_grammar.py',
    'soul_composition.py',
    'progressive_arrangement.py',
    'progressive_features.py',
    'color_dna.py',
    'seasonal_rules.py',
    'identity_motif.py',
    'living_color.py',
    'primitives.py',
    'grammar.py',
    # Shared helpers extracted by the refactor (M1 / M4 / M7).  They are on
    # the render path, so a change to them has to invalidate a workspace.
    'geometry.py',
    'midi_io.py',
    # Rendering.
    'render_soundfont.py',
    'compose_blueprint.py',
    'build_studio.py',
    'build_progressive_arrangement.py',
)

UI_FILES = (
    'studio.html',
    'studio.css',
    'studio.js',
    'soul_experience.js',
    'soul_interaction.js',
    'soul_hero.js',
    'progressive_revelation.js',
    'living_color.js',
    'role_editor.js',
)

# H4 + L3: the archived reference snapshots used to live next to the
# production modules.  They are now in `_archive/` so that they can no
# longer be mistaken for production code (and so that the "hash
# everything in this folder" pattern could not pick them up).
#
# They are *not* part of the render pipeline, so they are not hashed and
# they are not loaded through the snapshot.  `build_color_contrast_review.py`
# imports them directly from `_archive/`.
ARCHIVED_REFERENCES = (
    'progressive_arrangement_v10_reference',
    'progressive_arrangement_v11_reference',
    'progressive_arrangement_v14_reference',
    'color_dna_v10_reference',
    'color_dna_v12_reference',
)

ARCHIVE_DIR = '_archive'


class EngineSnapshot(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Freeze the engine modules and serve them as immutable import sources.

    The snapshot has two distinct jobs, and they must not be conflated:

    *   **Import** — every ``*.py`` module in the engine folder has to be
        importable through the snapshot, so that a module cannot change
        half-way through a render.  This is what
        ``test_engine_snapshot.py`` exercises.
    *   **Hashing** — only the modules that can actually change the
        *rendered output* may take part in the workspace-validity hash.
        Hashing the test suites, the one-off build scripts or the archived
        reference snapshots meant that editing any of them invalidated
        **every** existing work and triggered a full rebuild (H4).
    """

    def __init__(self, root):
        self.root = Path(root)
        # Import set: every module and UI asset that can be served through
        # the snapshot.  This keeps the "immutable source bytes" guarantee
        # for the whole engine folder.
        importable = sorted(self.root.glob('*.py')) + sorted((self.root / 'ui').glob('*'))
        # Hash set: only the modules that can actually change the rendered
        # output (H4).
        hashed = [self.root / name for name in ENGINE_MODULES]
        hashed += [self.root / 'ui' / name for name in UI_FILES]
        for _ in range(3):
            self.content = {p.relative_to(self.root).as_posix(): p.read_bytes()
                            for p in importable if p.is_file()}
            if all(p.read_bytes() == self.content[p.relative_to(self.root).as_posix()]
                   for p in hashed if p.is_file()):
                break
        else:
            raise RuntimeError('主线正在保存，请稍后重试。')
        # Only the render-relevant modules are hashed, so touching a test
        # file or an archived reference no longer invalidates every work.
        self.hashes = {p.relative_to(self.root).as_posix():
                       hashlib.sha256(self.content[p.relative_to(self.root).as_posix()]).hexdigest()
                       for p in hashed if p.is_file()}

    def install(self):
        sys.meta_path.insert(0, self)
        return self

    def find_spec(self, fullname, path=None, target=None):
        if '.' not in fullname and fullname + '.py' in self.content:
            return importlib.util.spec_from_loader(fullname, self, origin=str(self.root / (fullname + '.py')))

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        filename = str(self.root / (module.__name__ + '.py'))
        module.__file__ = filename
        exec(compile(self.content[module.__name__ + '.py'], filename, 'exec'), module.__dict__)
