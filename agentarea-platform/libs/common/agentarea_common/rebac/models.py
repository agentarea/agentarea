"""Typed models for Ory Keto relation tuples.

Mirrors the Keto relation-tuple JSON shape. A tuple is
``<namespace>:<object>#<relation>@<subject>`` where the subject is either a
direct ``subject_id`` (e.g. ``Agent:writer-1``) or a ``subject_set`` (a
userset such as ``Workspace:default#members``).
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class SubjectSet(BaseModel):
    """A userset subject: every subject related to ``object`` by ``relation``."""

    namespace: str
    object: str
    relation: str

    def to_keto(self) -> dict[str, str]:
        """Serialize to the Keto subject_set JSON shape."""
        return {
            "namespace": self.namespace,
            "object": self.object,
            "relation": self.relation,
        }

    def __str__(self) -> str:
        """Render as ``namespace:object#relation``."""
        return f"{self.namespace}:{self.object}#{self.relation}"


class RelationTuple(BaseModel):
    """A single Keto relation tuple."""

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

    def to_keto(self) -> dict:
        """Serialize to the Keto relation-tuple JSON body."""
        body: dict = {
            "namespace": self.namespace,
            "object": self.object,
            "relation": self.relation,
        }
        if self.subject_id is not None:
            body["subject_id"] = self.subject_id
        elif self.subject_set is not None:
            body["subject_set"] = self.subject_set.to_keto()
        return body

    @classmethod
    def from_keto(cls, data: dict) -> RelationTuple:
        """Build a RelationTuple from a Keto relation-tuple JSON object."""
        subject_set = data.get("subject_set")
        return cls(
            namespace=data["namespace"],
            object=data["object"],
            relation=data["relation"],
            subject_id=data.get("subject_id"),
            subject_set=SubjectSet(**subject_set) if subject_set else None,
        )

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

    def to_params(self) -> dict[str, str]:
        """Serialize to Keto read-API query parameters."""
        params: dict[str, str] = {}
        if self.namespace is not None:
            params["namespace"] = self.namespace
        if self.object is not None:
            params["object"] = self.object
        if self.relation is not None:
            params["relation"] = self.relation
        if self.subject_id is not None:
            params["subject_id"] = self.subject_id
        if self.subject_set is not None:
            params["subject_set.namespace"] = self.subject_set.namespace
            params["subject_set.object"] = self.subject_set.object
            params["subject_set.relation"] = self.subject_set.relation
        params["page_size"] = str(self.page_size)
        if self.page_token:
            params["page_token"] = self.page_token
        return params


class CheckResult(BaseModel):
    """Result of a Keto permission check."""

    allowed: bool


class ExpandNode(BaseModel):
    """A node in a Keto expand tree (the derivation of a permission)."""

    type: str
    subject_id: str | None = None
    subject_set: SubjectSet | None = None
    children: list[ExpandNode] = Field(default_factory=list)

    @classmethod
    def from_keto(cls, data: dict) -> ExpandNode:
        """Build an ExpandNode tree from a Keto expand response."""
        subject_set = data.get("subject_set")
        return cls(
            type=data.get("type", "unknown"),
            subject_id=data.get("subject_id"),
            subject_set=SubjectSet(**subject_set) if subject_set else None,
            children=[cls.from_keto(c) for c in data.get("children") or []],
        )
