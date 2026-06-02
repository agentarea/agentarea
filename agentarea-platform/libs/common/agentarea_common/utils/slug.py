"""Slug generation utilities for workspace-scoped immutable identifiers.

A slug is a human-readable URL-safe identifier derived from a name. The
generator here is intentionally simple — ASCII-only, lowercase, hyphenated
— so that slugs are stable across browsers, shells, and storage backends.

Slugs are *not* a replacement for UUIDs: they are workspace-scoped, derived
once at creation time, and never re-derived on rename.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable

_MAX_SLUG_LENGTH = 100
_FALLBACK_SLUG = "item"
_MAX_COLLISION_SUFFIX = 999


def generate_slug(name: str) -> str:
    """Derive a slug from a human-readable name.

    Steps:
      1. NFKD-normalize and drop non-ASCII bytes (transliterates accents,
         drops scripts that have no ASCII equivalent like Cyrillic/CJK).
      2. Lowercase.
      3. Replace any run of non-alphanumeric characters with a single
         hyphen.
      4. Strip leading/trailing hyphens.
      5. Truncate to ``_MAX_SLUG_LENGTH`` characters and re-strip trailing
         hyphens introduced by the cut.
      6. If the result is empty (e.g. all-emoji or all-Cyrillic input),
         return ``"item"`` as a safe placeholder — caller is expected to
         disambiguate via :func:`ensure_unique_slug`.
    """
    if not isinstance(name, str):
        name = str(name)

    # 1. ASCII transliteration. NFKD splits combining marks; ascii/ignore
    # drops anything that isn't representable.
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")

    # 2 + 3. Lowercase and collapse runs of non-alphanumeric to a single '-'.
    lowered = ascii_name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered)

    # 4. Trim hyphens at the edges.
    slug = slug.strip("-")

    # 5. Truncate, then re-strip in case truncation introduced a trailing '-'.
    if len(slug) > _MAX_SLUG_LENGTH:
        slug = slug[:_MAX_SLUG_LENGTH].rstrip("-")

    # 6. Fallback for empty results (all-emoji, all-non-ASCII, all-punct).
    if not slug:
        return _FALLBACK_SLUG

    return slug


def ensure_unique_slug(base: str, exists: Callable[[str], bool]) -> str:
    """Return ``base`` if it is free, otherwise ``base-2``, ``base-3``, ...

    ``exists`` is a synchronous predicate that returns True when the
    candidate is already in use. Callers backed by async storage should
    wrap their lookup themselves; see
    :func:`ensure_unique_slug_async` callers in the service layer.

    Raises:
        ValueError: if every candidate up to ``base-999`` is taken. This
            guards against pathological loops while still leaving a very
            generous ceiling for normal workspaces.
    """
    if not exists(base):
        return base

    for suffix in range(2, _MAX_COLLISION_SUFFIX + 1):
        candidate = f"{base}-{suffix}"
        if not exists(candidate):
            return candidate

    raise ValueError(
        f"Exhausted collision suffixes (-2..-{_MAX_COLLISION_SUFFIX}) for slug base '{base}'"
    )
