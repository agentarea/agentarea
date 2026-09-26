from datetime import datetime, timedelta, timezone
from typing import Annotated

import pytest
from agentarea_common.utils.types import NaiveUtcDatetime, NotNull
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class _Patch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str | None, NotNull] = Field(default=None, min_length=1)
    description: str | None = None


def test_an_omitted_not_null_field_stays_unset() -> None:
    assert _Patch.model_validate({}).model_dump(exclude_unset=True) == {}


def test_an_explicit_null_is_refused_where_the_column_is_not_null() -> None:
    with pytest.raises(ValidationError):
        _Patch.model_validate({"name": None})


def test_field_constraints_still_apply() -> None:
    with pytest.raises(ValidationError):
        _Patch.model_validate({"name": ""})


def test_the_published_schema_does_not_offer_null() -> None:
    properties = _Patch.model_json_schema()["properties"]

    assert properties["name"]["type"] == "string"
    assert "anyOf" not in properties["name"]
    assert {"type": "null"} in properties["description"]["anyOf"]


class _Window(BaseModel):
    since: NaiveUtcDatetime


def test_an_offset_datetime_becomes_naive_utc() -> None:
    plus_three = timezone(timedelta(hours=3))

    since = _Window(since=datetime(2026, 1, 1, 12, 0, tzinfo=plus_three)).since

    assert since == datetime(2026, 1, 1, 9, 0)
    assert since.tzinfo is None


def test_a_naive_datetime_is_taken_as_utc() -> None:
    assert _Window(since=datetime(2026, 1, 1, 12, 0)).since == datetime(2026, 1, 1, 12, 0)
    assert _Window(since="2026-01-01T12:00:00Z").since == datetime(2026, 1, 1, 12, 0)
