from ...common.events.broker import EventBroker
from .application.service import AgentService
from .infrastructure.repository import AgentRepository

class AgentModule:
    def __init__(self, event_broker: EventBroker):
        self.event_broker = event_broker
    