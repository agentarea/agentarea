
from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship


class ProviderSpec(BaseModel, WorkspaceScopedMixin):
    """Provider specification - defines available provider types (OpenAI, Anthropic, etc.)"""
    __tablename__ = "provider_specs"

    provider_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)  # openai, anthropic
    name: Mapped[str] = mapped_column(String, nullable=False)  # OpenAI, Anthropic
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    provider_type: Mapped[str] = mapped_column(String, nullable=False)  # for LiteLLM compatibility
    icon: Mapped[str | None] = mapped_column(String, nullable=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    provider_configs = relationship("ProviderConfig", back_populates="provider_spec", cascade="all, delete-orphan")
    model_specs = relationship("ModelSpec", back_populates="provider_spec", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<ProviderSpec {self.name} ({self.provider_key})>"


class ProviderConfig(BaseModel, WorkspaceScopedMixin):
    """Provider configuration - user's configured instance of a provider with API key"""
    __tablename__ = "provider_configs"

    provider_spec_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("provider_specs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)  # "My OpenAI", "Work OpenAI"
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    api_key: Mapped[str] = mapped_column(String, nullable=False)
    endpoint_url: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Relationships
    provider_spec = relationship("ProviderSpec", back_populates="provider_configs")
    model_instances = relationship("ModelInstance", back_populates="provider_config", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<ProviderConfig {self.name} ({self.id})>"


class ModelSpec(BaseModel, WorkspaceScopedMixin):
    """Model specification - defines available models for each provider"""
    __tablename__ = "model_specs"
    __table_args__ = (
        UniqueConstraint('provider_spec_id', 'model_name', name='uq_model_specs_provider_model'),
    )

    provider_spec_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("provider_specs.id", ondelete="CASCADE"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(String, nullable=False)  # gpt-4, claude-3-opus
    display_name: Mapped[str] = mapped_column(String, nullable=False)  # GPT-4, Claude 3 Opus
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    context_window: Mapped[int] = mapped_column(Integer, nullable=False, default=4096)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    provider_spec = relationship("ProviderSpec", back_populates="model_specs")
    model_instances = relationship("ModelInstance", back_populates="model_spec", cascade="all, delete-orphan")

    def __repr__(self):
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

    # Relationships
    provider_config = relationship("ProviderConfig", back_populates="model_instances")
    model_spec = relationship("ModelSpec", back_populates="model_instances")

    def __repr__(self):
        return f"<ModelInstance {self.name} ({self.id})>"


# Legacy models - kept for backward compatibility during migration
# TODO: Remove these after migration is complete

class LLMProvider(BaseModel, WorkspaceScopedMixin):
    """Legacy LLM Provider model - deprecated, use ProviderSpec instead"""
    __tablename__ = "llm_providers"

    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    description: Mapped[str] = mapped_column(String, nullable=True)
    provider_type: Mapped[str] = mapped_column(String, nullable=False)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    models = relationship("LLMModel", back_populates="provider")

    def __repr__(self):
        return f"<LLMProvider {self.name} ({self.id})>"


class LLMModel(BaseModel, WorkspaceScopedMixin):
    """Legacy LLM Model - deprecated, use ModelSpec instead"""
    __tablename__ = "llm_models"

    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    provider_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("llm_providers.id"), nullable=False
    )
    model_type: Mapped[str] = mapped_column(String, nullable=False)
    endpoint_url: Mapped[str | None] = mapped_column(String, nullable=True)
    context_window: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    provider = relationship("LLMProvider", back_populates="models")
    instances = relationship("LLMModelInstance", back_populates="model")

    def __repr__(self):
        return f"<LLMModel {self.name} ({self.id})>"


class LLMModelInstance(BaseModel, WorkspaceScopedMixin):
    """Legacy LLM Model Instance - deprecated, use ModelInstance instead"""
    __tablename__ = "llm_model_instances"

    model_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("llm_models.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    api_key: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    model = relationship("LLMModel", back_populates="instances")

    def __repr__(self):
        return f"<LLMModelInstance {self.name} ({self.id})>"
