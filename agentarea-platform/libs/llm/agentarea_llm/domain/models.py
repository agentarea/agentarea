from decimal import Decimal
from importlib import import_module
from uuid import UUID

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from agentarea_common.constants import MANAGED_BY_PLATFORM, PLATFORM_WORKSPACE_ID
from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

# Register encrypted_secrets on the shared metadata before SQLAlchemy resolves
# the api_key_secret_id foreign key below. Importing this module alone would
# otherwise leave the target table unknown, which surfaces as
# NoReferencedTableError the first time any mapper is configured.
import_module("agentarea_secrets.models")

# Re-exported so callers reading about ``ProviderConfig.managed_by`` find its one
# legal value next to the column. Defined in agentarea_common because the execution
# library needs the same constant and does not depend on this one.
#
# A named constant rather than a literal at each site because three unrelated
# decisions read it — cross-workspace visibility, write refusal, and whose budget a
# run spends — and a typo in any one of them fails silently in the permissive
# direction.
__all__ = [
    "MANAGED_BY_PLATFORM",
    "ModelInstance",
    "ModelSpec",
    "ProviderConfig",
    "ProviderSpec",
]


class ProviderSpec(BaseModel, WorkspaceScopedMixin):
    """Provider specification - defines available provider types (OpenAI, Anthropic, etc.)"""

    __tablename__ = "provider_specs"

    provider_key: Mapped[str] = mapped_column(
        String, nullable=False, unique=True
    )  # openai, anthropic
    name: Mapped[str] = mapped_column(String, nullable=False)  # OpenAI, Anthropic
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    provider_type: Mapped[str] = mapped_column(String, nullable=False)  # for LiteLLM compatibility
    icon: Mapped[str | None] = mapped_column(String, nullable=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Whether this provider type authenticates at all. False for the local ones
    # (Ollama and friends), which listen on an unauthenticated endpoint — asking
    # for a key there leaves the user with a required field they can only satisfy
    # by inventing a value.
    requires_api_key: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships (lazy="selectin" for async compatibility)
    provider_configs = relationship(
        "ProviderConfig",
        back_populates="provider_spec",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    model_specs = relationship(
        "ModelSpec", back_populates="provider_spec", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self):
        """Return a concise string representation for debugging."""
        return f"<ProviderSpec {self.name} ({self.provider_key})>"


class ProviderConfig(BaseModel, WorkspaceScopedMixin):
    """Provider configuration - user's configured instance of a provider with API key"""

    __tablename__ = "provider_configs"

    provider_spec_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("provider_specs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)  # "My OpenAI", "Work OpenAI"
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    # The name of the secret holding the key. Resolution goes through this, here
    # and in the worker's execution activities.
    api_key: Mapped[str | None] = mapped_column(String, nullable=True)
    # The same secret as a relationship. Carries what a name cannot: the
    # database refuses to delete a secret while a config still points at it,
    # and the catalog can list the configs using one without parsing names.
    api_key_secret_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("encrypted_secrets.id", ondelete="RESTRICT"),
        nullable=True,
    )
    endpoint_url: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Who owns this configuration's credentials.
    #
    #   NULL        -- the tenant's own. They supplied the key, they may change or
    #                  delete it, and it is visible only inside their workspace.
    #   "platform"  -- the deployment operator's. The key is theirs, the
    #                  configuration is readable from every workspace, and the API
    #                  refuses every tenant write to it (see ProviderService).
    #
    # The second case is what lets an operator offer models nobody has to bring a
    # key for: our hosted service, and equally a company handing one corporate key
    # to all of its internal workspaces.
    #
    # It is deliberately one column rather than a flag plus a workspace convention.
    # "Whose credentials are these" and "who may see it" and "who may edit it" are
    # the same question, and answering it in three places is how they come to
    # disagree.
    managed_by: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Relationships (lazy="selectin" for async compatibility)
    provider_spec = relationship("ProviderSpec", back_populates="provider_configs", lazy="selectin")
    model_instances = relationship(
        "ModelInstance",
        back_populates="provider_config",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self):
        """Return a concise string representation for debugging."""
        return f"<ProviderConfig {self.name} ({self.id})>"


class ModelSpec(BaseModel, WorkspaceScopedMixin):
    """Model specification - defines available models for each provider"""

    __tablename__ = "model_specs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "provider_spec_id",
            "model_name",
            name="uq_model_specs_workspace_provider_model",
        ),
    )

    provider_spec_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("provider_specs.id", ondelete="CASCADE"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(String, nullable=False)  # gpt-4, claude-3-opus
    display_name: Mapped[str] = mapped_column(String, nullable=False)  # GPT-4, Claude 3 Opus
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    context_window: Mapped[int] = mapped_column(Integer, nullable=False)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_cost_per_token: Mapped[Decimal | None] = mapped_column(Numeric(20, 12), nullable=True)
    output_cost_per_token: Mapped[Decimal | None] = mapped_column(Numeric(20, 12), nullable=True)
    supports_function_calling: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, default=False
    )
    supports_vision: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)
    supports_reasoning: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)
    default_context_strategy: Mapped[str | None] = mapped_column(
        String, nullable=True, default=None
    )  # "static", "hybrid", "dynamic" — resolved per agent execution
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships (lazy="selectin" for async compatibility)
    provider_spec = relationship("ProviderSpec", back_populates="model_specs", lazy="selectin")
    model_instances = relationship(
        "ModelInstance", back_populates="model_spec", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self):
        """Return a concise string representation for debugging."""
        return f"<ModelSpec {self.display_name} ({self.model_name})>"


class ModelInstance(BaseModel, WorkspaceScopedMixin):
    """Model instance - active user model instances combining provider config and model spec"""

    __tablename__ = "model_instances"

    provider_config_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("provider_configs.id", ondelete="CASCADE"), nullable=False
    )
    model_spec_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("model_specs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)  # User-friendly name
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Relationships (lazy="selectin" for async compatibility)
    provider_config = relationship(
        "ProviderConfig", back_populates="model_instances", lazy="selectin"
    )
    model_spec = relationship("ModelSpec", back_populates="model_instances", lazy="selectin")

    def foreign_part(self) -> str | None:
        """Name the part this instance's workspace may not use, if any.

        The spec carries the price the run is billed at and the config carries
        the credentials, so neither may come from a workspace other than the
        instance's own, except the platform's.
        """
        if getattr(self.provider_config, "managed_by", None) != MANAGED_BY_PLATFORM and (
            getattr(self.provider_config, "workspace_id", None) != self.workspace_id
        ):
            return "provider_config"
        if getattr(self.model_spec, "workspace_id", None) not in (
            self.workspace_id,
            PLATFORM_WORKSPACE_ID,
        ):
            return "model_spec"
        return None

    def __repr__(self):
        """Return a concise string representation for debugging."""
        return f"<ModelInstance {self.name} ({self.id})>"
