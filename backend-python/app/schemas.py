"""Shared API schema base: JSON is camelCase on the wire, snake_case in Python."""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class RequestModel(ApiModel):
    # Unknown fields (including any client-supplied userId) are rejected, not ignored.
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")
