"""Slug generation for workspaces.

A workspace slug is the human-readable handle used in URLs (``/w/{slug}``).
It must be globally unique; uniqueness is resolved by the service layer,
this module only produces a clean, URL-safe base.
"""

import re

SLUG_MAX_LENGTH = 40


def slugify(text: str, *, fallback: str = "workspace") -> str:
    """Lowercase, hyphenate and trim ``text`` into a URL-safe slug.

    Never returns an empty string — falls back to ``fallback`` when the
    input has no slug-able characters (e.g. all punctuation).
    """
    base = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower())
    base = re.sub(r"-{2,}", "-", base).strip("-")[:SLUG_MAX_LENGTH].strip("-")
    return base or fallback
