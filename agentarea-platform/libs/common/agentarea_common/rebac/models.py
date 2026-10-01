"""Typed models for ReBAC relation tuples.

A tuple is ``<namespace>:<object>#<relation>@<subject>`` where the subject is
either a direct ``subject_id`` (e.g. ``Agent:writer-1``) or a ``subject_set``
(a userset such as ``Workspace:default#members``).
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class SubjectSet(BaseModel):
    """A userset subject: every subject related to ``object`` by ``relation``."""

    namespace: str
    object: str
    relation: str

    def __str__(self) -> str:
        """Render as ``namespace:object#relation``."""
        return f"{self.namespace}:{self.object}#{self.relation}"


class RelationTuple(BaseModel):
    """A single relation tuple."""

    namespace: str
    object: str
    relation: str
    subject_id: str | None = None
    subject_set: SubjectSet | None = None

    @model_validator(mode="after")
    def _exactly_one_subject(self) -> RelationTuple:
        if (self.subject_id is None) == (self.subject_set is None):
            raise ValueError("exactly one of subject_id or subject_set must be set")
        return self

    def __str__(self) -> str:
        """Render as ``namespace:object#relation@subject``."""
        subject = self.subject_id if self.subject_id is not None else str(self.subject_set)
        return f"{self.namespace}:{self.object}#{self.relation}@{subject}"


class RelationQuery(BaseModel):
    """Filter for listing relation tuples (all fields optional)."""

    namespace: str | None = None
    object: str | None = None
    relation: str | None = None
    subject_id: str | None = None
    subject_set: SubjectSet | None = None
    page_size: int = Field(default=100, ge=1, le=500)
    page_token: str | None = None


class CheckResult(BaseModel):
    """Result of a permission check."""

    allowed: bool
