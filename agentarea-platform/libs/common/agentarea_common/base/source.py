from enum import StrEnum


class SourceKind(StrEnum):
    """Provenance of a resource: where its definition came from."""

    OFFICIAL = "official"  # seeded by the platform
    WORKSPACE_CUSTOM = "workspace_custom"  # created by a user/team
    IMPORTED = "imported"  # imported (e.g. via a bundle)


def is_builtin(entity: object) -> bool:
    """True if the entity is platform-official (built-in)."""
    return getattr(entity, "source", None) == SourceKind.OFFICIAL
