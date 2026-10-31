"""Egress exits: named routes out of the network an MCP instance can leave through.

An exit is a proxy whose address the destination sees: the workspace's own (a
customer or purchased proxy) or one the platform runs. An instance binds one with
``json_spec.egress_exit = "<exit id>"``; without the enterprise extension nothing
enforces the binding.
"""

from importlib import import_module
from uuid import UUID

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from agentarea_common.constants import MANAGED_BY_PLATFORM
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ColumnElement,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    or_,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

# Registers encrypted_secrets on the shared metadata before the password
# foreign key below is resolved.
import_module("agentarea_secrets.models")

EGRESS_EXIT_SPEC_KEY = "egress_exit"


class EgressExit(BaseModel, WorkspaceScopedMixin):
    __tablename__ = "egress_exits"

    #: Governed by the authorization graph: creating one writes
    #: ``resource:<id>`` tuples so its creator can reach it afterwards.
    __graph_resource__ = True

    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_egress_exits_workspace_name"),
        CheckConstraint(
            "upstream_url IS NOT NULL OR (COALESCE(managed_by, '') = 'platform' AND via IS NOT NULL)",
            name="ck_egress_exits_route",
        ),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # scheme://host:port of the proxy, with no credentials in it. NULL only on a
    # platform exit that leaves straight from its hop.
    upstream_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_secret_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("encrypted_secrets.id", ondelete="RESTRICT"),
        nullable=True,
    )
    # A hop the egress proxy's own configuration defines; platform exits only.
    via: Mapped[str | None] = mapped_column(String(63), nullable=True)
    remote_dns: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_plaintext_credentials: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # ``"platform"``: an exit the deployment supplies to every workspace, written
    # only by the operator. NULL: the workspace's own.
    managed_by: Mapped[str | None] = mapped_column(String(32), nullable=True)

    @property
    def is_platform(self) -> bool:
        return self.managed_by == MANAGED_BY_PLATFORM

    @classmethod
    def workspace_visibility(cls, workspace_id: str) -> ColumnElement[bool]:
        """The workspace's own exits, plus the platform's."""
        return or_(cls.workspace_id == workspace_id, cls.managed_by == MANAGED_BY_PLATFORM)
