from vm_agent.src.network.agent_connection import AgentConnection


class ReceivablePackiet(AgentConnection):
    def __init__(self, config):
        super().__init__(config)    