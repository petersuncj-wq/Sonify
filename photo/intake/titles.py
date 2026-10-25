"""Shared validation for user-supplied titles.

Two entry points accept a user-chosen title:

  * `Pipeline.rename()` — renaming a local work (M11),
  * `community.publish()` — publishing a work to the community (L5).

Both need the *same* rules, otherwise a title that the community rejects
would be accepted locally (and vice versa), and the two lists would show
inconsistent content.

The rules are deliberately strict:

  * 1–60 characters after stripping surrounding whitespace,
  * letters, digits, CJK ideographs, spaces and a small set of harmless
    punctuation marks,
  * **no** control characters (they break line rendering),
  * **no** bidirectional override characters (U+202A–U+202E,
    U+2066–U+2069) — they can visually reorder a list and spoof a name,
  * **no** markup characters, so a title can never be injected into HTML.
"""
from __future__ import annotations

import unicodedata

MAX_TITLE_LENGTH = 60

# Punctuation that is safe to render anywhere.
#
# Note: `<` and `>` are deliberately *not* allowed.  The community and the
# console both render titles with `textContent`, so markup cannot execute
# there — but a title may also be embedded into an SVG, an attribute or a
# generated document elsewhere in the project, and rejecting the markup
# characters outright removes that whole class of risk.
_ALLOWED_PUNCTUATION = set('_-—–·、。，！？：；（）《》〈〉【】….,!?:\'"()[]{}#/&+*=%@$^~`|<>') - set('<>')

# Bidirectional override / isolate characters that must be rejected.
_BIDI_OVERRIDES = frozenset(
    '‪‫‬‭‮'
    '⁦⁧⁨⁩'
    '؜'
)

# Unicode general categories that must never appear in a title.
_FORBIDDEN_CATEGORIES = frozenset({'Cc', 'Cf', 'Co', 'Cs', 'Cn', 'Zl', 'Zp'})


class TitleError(ValueError):
    """Raised when a title does not satisfy the whitelist."""


def is_forbidden(char: str) -> bool:
    """True if `char` is a control / format / bidi-override character."""
    if char in _BIDI_OVERRIDES:
        return True
    return unicodedata.category(char) in _FORBIDDEN_CATEGORIES


def sanitize_title(title, max_length: int = MAX_TITLE_LENGTH) -> str:
    """Validate and normalize a user-supplied title.

    Returns the cleaned title.  Raises `TitleError` (a `ValueError`) when
    the title is empty, too long or contains a forbidden character.
    """
    if title is None:
        raise TitleError('请输入作品名。')
    if not isinstance(title, str):
        raise TitleError('作品名格式无效。')
    # Normalize to NFC so that visually identical titles compare equal and
    # cannot smuggle decomposed combining marks past the whitelist.
    clean = unicodedata.normalize('NFC', title).strip()
    if not clean:
        raise TitleError('请输入作品名。')
    if len(clean) > max_length:
        raise TitleError(f'作品名最多 {max_length} 字。')
    for char in clean:
        if is_forbidden(char):
            raise TitleError('作品名包含不可见或方向控制字符，请重新输入。')
        if char.isalnum() or char.isspace():
            continue
        if char in _ALLOWED_PUNCTUATION:
            continue
        raise TitleError('作品名含有不支持的字符，请重新输入。')
    return clean


__all__ = ['sanitize_title', 'is_forbidden', 'TitleError', 'MAX_TITLE_LENGTH']
