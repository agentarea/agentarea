from dataclasses import dataclass
from uuid import UUID

from agentarea.common.events.base_events import DomainEvent


@dataclass
class LLMModelCreated(DomainEvent):
    model_id: UUID
    name: str
    provider: str
    model_type: str


@dataclass
class LLMModelUpdated(DomainEvent):
    model_id: UUID
    name: str
    provider: str
    model_type: str


@dataclass
class LLMModelDeleted(DomainEvent):
    model_id: UUID


@dataclass
class LLMModelInstanceCreated(DomainEvent):
    instance_id: UUID
    model_id: UUID
    name: str


@dataclass
class LLMModelInstanceUpdated(DomainEvent):
    instance_id: UUID
    model_id: UUID
    name: str


@dataclass
class LLMModelInstanceDeleted(DomainEvent):
    instance_id: UUID 