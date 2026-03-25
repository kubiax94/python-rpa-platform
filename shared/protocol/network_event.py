from typing import Literal
from pydantic import Field, ConfigDict

from shared.protocol.abstract_event import AbstractEvent
from shared.protocol.net_headers import NetHeaders


# This Event is responsible for transport layer, every event related to network,
# should derived from this class
class NetworkEvent(AbstractEvent):
    headers: NetHeaders = Field(default_factory=NetHeaders)
    _owner: Literal["client", "server"] = "client"
    data: dict

    model_config = ConfigDict(extra="ignore")

    @property
    def corelation_id(self) -> str:
        return self._headers.corelation_id
    
    @corelation_id.setter
    def corelation_id(self, corelation_id: str):
        self._headers.corelation_id = corelation_id
