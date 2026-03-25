from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any
import uuid, socket, platform, time

from pydantic import Field, BaseModel



class NetHeaders(BaseModel):
    protocol_version: str = Field(default="1.0.0")
    content_type: str = Field(default="application/json")
    encoding: str = Field(default="utf-8")
    authorization: Optional[str] = Field(default=None)

    host: str = Field(default_factory=socket.gethostname)
    platform: str = Field(default_factory=platform.system)
    timestamp: float = Field(default_factory=time.time)

    

    @classmethod
    def add_bearer_auth_header(cls, secret: str) -> "NetHeaders":
        return cls(authorization=f"Bearer {secret}")