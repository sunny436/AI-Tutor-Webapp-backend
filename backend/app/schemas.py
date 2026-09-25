"""Shared API schema base: JSON is camelCase on the wire, snake_case in Python."""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class RequestModel(ApiModel):
    # Unknown fields (including any client-supplied userId) are rejected, not ignored.
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


def check_set_reset(changes: BaseModel, reset: list[str]) -> None:
    """The rules every versioned edit shares (docs/api-contract.md, "Versioned edits"): `null`
    is not a value (reset the field instead), and each field has at most one meaning."""
    explicit = changes.model_fields_set
    if any(getattr(changes, name) is None for name in explicit):
        raise ValueError("null is not a value in `set`; list the field in `reset` instead")
    fields = type(changes).model_fields
    if {fields[name].alias or name for name in explicit} & set(reset):
        raise ValueError("a field cannot be both set and reset")
    if len(set(reset)) != len(reset):
        raise ValueError("a field is listed twice in `reset`")
