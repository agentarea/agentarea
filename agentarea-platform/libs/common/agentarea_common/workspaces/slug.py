"""Slug generation for workspaces.

A workspace slug is the human-readable handle used in URLs (``/w/{slug}``).
It must be globally unique; uniqueness is resolved by the service layer,
this module only produces a clean, URL-safe base.
"""

import re

SLUG_MAX_LENGTH = 40

# What a URL may name as a workspace. Wider than ``slugify`` output: collision
# suffixes (``-2``) and slugs backfilled from ids fit the 120-char column.
WORKSPACE_SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
WORKSPACE_SLUG_COLUMN_LENGTH = 120

# The shape of a workspace id. A reference in this shape names a workspace by
# id; a slug in this shape could impersonate the workspace that has it as id
# (a personal workspace's id is its owner's user id), so none is ever minted.
_UUID_SHAPED = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def is_uuid_shaped(reference: str) -> bool:
    """Whether ``reference`` looks like a workspace id rather than a slug."""
    return bool(_UUID_SHAPED.match(reference.lower()))


def is_valid_workspace_slug(reference: str) -> bool:
    """Whether ``reference`` could name a workspace in a URL."""
    return (
        len(reference) <= WORKSPACE_SLUG_COLUMN_LENGTH
        and re.match(WORKSPACE_SLUG_PATTERN, reference) is not None
    )


def slugify(text: str, *, fallback: str = "workspace") -> str:
    """Lowercase, hyphenate and trim ``text`` into a URL-safe slug.

    Never returns an empty string — falls back to ``fallback`` when the
    input has no slug-able characters (e.g. all punctuation) — and never a
    UUID-shaped one, which is suffixed so it cannot pose as a workspace id.
    """
    base = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower())
    base = re.sub(r"-{2,}", "-", base).strip("-")[:SLUG_MAX_LENGTH].strip("-")
    base = base or fallback
    return f"{base}-ws" if is_uuid_shaped(base) else base
