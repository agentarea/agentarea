def is_builtin(entity: object) -> bool:
    """True if the entity is a read-only catalog projection (built-in).

    Per ADR-003 there are no persisted built-in rows. Built-in agents/skills
    exist only in the registry catalog; a service ``list()`` result represents
    them via a transient catalog *projection* marked with ``is_catalog = True``
    (set in ``_project_catalog_item`` / ``_project_catalog_skill``).

    Only that projection is "built-in". Copy-on-write forks carry a
    ``registry_item_id`` link to the catalog item they were forked from, but
    they are persisted, user-owned content that IS exportable -- so they are NOT
    built-in. User-created rows (no ``registry_item_id``) are likewise owned and
    exportable. Persisted instances/configs are never projections and are never
    built-in.
    """
    return bool(getattr(entity, "is_catalog", False))
