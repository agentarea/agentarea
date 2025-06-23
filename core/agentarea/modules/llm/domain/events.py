from uuid import UUID

from agentarea.common.events.base_events import DomainEvent


class LLMModelCreated(DomainEvent):
    def __init__(self, model_id: UUID, name: str, provider: str, model_type: str) -> None:
        super().__init__()
        self.model_id = model_id
        self.name = name
        self.provider = provider
        self.model_type = model_type


class LLMModelUpdated(DomainEvent):
    def __init__(self, model_id: UUID, name: str, provider: str, model_type: str) -> None:
        super().__init__()
        self.model_id = model_id
        self.name = name
        self.provider = provider
        self.model_type = model_type


class LLMModelDeleted(DomainEvent):
    def __init__(self, model_id: UUID) -> None:
        super().__init__()
        self.model_id = model_id


class LLMModelInstanceCreated(DomainEvent):
    def __init__(self, instance_id: UUID, model_id: UUID, name: str) -> None:
        super().__init__()
        self.instance_id = instance_id
        self.model_id = model_id
        self.name = name


class LLMModelInstanceUpdated(DomainEvent):
    def __init__(self, instance_id: UUID, model_id: UUID, name: str) -> None:
        super().__init__()
        self.instance_id = instance_id
        self.model_id = model_id
        self.name = name


class LLMModelInstanceDeleted(DomainEvent):
    def __init__(self, instance_id: UUID) -> None:
        super().__init__()
        self.instance_id = instance_id
