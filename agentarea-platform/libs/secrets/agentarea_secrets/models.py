"""Catalog tables.

`encrypted_secrets` predates the catalog: it was a value store keyed by
`(workspace_id, secret_name)`, and the name was synthesised from whatever owned
the secret. It keeps that name and that role, and gains the metadata a catalog
needs, rather than growing a second table beside it — Airflow, n8n, GitLab and
Infisical all keep metadata and ciphertext in one row, and splitting them means
the link between the two is a natural key that rename and delete have to keep
in step.
"""

from typing import Any
from uuid import UUID

from agentarea_common.base.models import BaseModel
from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column


class EncryptedSecret(BaseModel):
    """A workspace secret: its metadata, and either its value or a reference to it."""

    __tablename__ = "encrypted_secrets"

    workspace_id: Mapped[str] = mapped_column(nullable=False, index=True)
    secret_name: Mapped[str] = mapped_column(nullable=False, index=True)

    # Null when the value lives in an external store; external_ref then says
    # where. The CHECK constraint keeps exactly one of the two populated.
    encrypted_value: Mapped[str | None] = mapped_column(nullable=True)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Null means a user created this secret directly and owns it. Set means the
    # platform minted it for the entity named here, which is also what decides
    # whether the secrets API will let anyone edit or delete it. Polymorphic by
    # design — the owner is in one of eight tables — so no foreign key.
    owner_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Populated once an external provider backs this secret; unused today.
    external_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    provider_binding_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    created_by: Mapped[str] = mapped_column(nullable=False)
    updated_by: Mapped[str | None] = mapped_column(nullable=True)

    __table_args__ = (
        UniqueConstraint("workspace_id", "secret_name", name="uq_encrypted_secrets_workspace_name"),
        # The secrets list is a user-facing view of user-owned secrets, and
        # managed rows outnumber them: every task input field mints one.
        Index(
            "ix_encrypted_secrets_user_owned",
            "workspace_id",
            postgresql_where=owner_type.is_(None),
        ),
    )


class SecretReference(BaseModel):
    """A consumer that resolves this secret, for consumers that cannot hold a foreign key.

    Where the consumer has a column of its own — `provider_configs.api_key` —
    that column carries a real foreign key and Postgres refuses the delete
    directly. Some consumers keep the reference inside a JSON document instead
    (`openapi_connections.custom_headers`, `mcp_server_instances.json_spec`),
    where no foreign key can reach. Those record it here, and the foreign key on
    `secret_id` enforces the same rule for them.
    """

    __tablename__ = "secret_references"

    workspace_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    secret_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("encrypted_secrets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    consumer_type: Mapped[str] = mapped_column(String(64), nullable=False)
    consumer_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Which slot on the consumer — a header name, an env var name.
    field: Mapped[str] = mapped_column(String(255), nullable=False)

    def __init__(
        self,
        workspace_id: str,
        secret_id: UUID,
        consumer_type: str,
        consumer_id: str,
        field: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.workspace_id = workspace_id
        self.secret_id = secret_id
        self.consumer_type = consumer_type
        self.consumer_id = consumer_id
        self.field = field

    __table_args__ = (
        UniqueConstraint(
            "secret_id",
            "consumer_type",
            "consumer_id",
            "field",
            name="uq_secret_references_consumer_slot",
        ),
    )
