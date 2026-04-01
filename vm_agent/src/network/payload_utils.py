from __future__ import annotations

from pydantic import BaseModel


def coerce_event_data(data, model_type):
    if isinstance(data, model_type):
        return data
    if isinstance(data, BaseModel):
        return model_type.model_validate(data.model_dump())
    return model_type.model_validate(data)