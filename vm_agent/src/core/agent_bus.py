from pyee import EventEmitter

from shared.protocol.abstract_event import AbstractEvent
from vm_agent.src.core.iagent_bus import IAgentBus


class AgentBus(EventEmitter, IAgentBus):
    def __init__(self):
        super().__init__()

    def emit_event(self, event: AbstractEvent) -> None:
        super().emit(event.type, event.data)