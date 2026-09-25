"""Unified money type for consistent monetary value handling.

All monetary values across the platform should use this type:
- Money — Decimal with Pydantic str serialization. Use for model fields, arithmetic, everything.
- to_money() — safe constructor from any numeric input
- to_optional_money() — strict constructor that keeps None (unknown) apart from zero
- serialize_money() — for dict/event contexts that bypass Pydantic
"""

from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import BeforeValidator, PlainSerializer


def _parse_money(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"{value!r} is not a money amount") from None


# Single money type: Decimal internally, serializes to str in Pydantic JSON.
# Use for all monetary fields — model fields, function args, internal storage.
Money = Annotated[
    Decimal,
    BeforeValidator(_parse_money),
    PlainSerializer(str, return_type=str),
]

ZERO: Decimal = Decimal("0")


def to_money(value: float | str | int | Decimal | None) -> Decimal:
    """Convert any numeric value to Money (Decimal).

    Converts via str to avoid float representation issues.
    Returns ZERO for None or invalid values.
    """
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return ZERO


def to_optional_money(value: float | str | int | Decimal | None) -> Decimal | None:
    """Convert a value that may be absent to Money, keeping None as None.

    For prices, where None means unknown and zero means free. Unlike to_money(),
    an unparseable value raises instead of becoming zero.
    """
    if value is None or isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def serialize_money(value: Decimal | float | str | int | None) -> str:
    """Serialize a money value to string for JSON/dict contexts.

    Use this when building dicts or event payloads that will be
    JSON-serialized outside of Pydantic (e.g. workflow events).
    Pydantic models with Money fields handle this automatically.
    """
    if value is None:
        return "0"
    if isinstance(value, Decimal):
        return str(value)
    try:
        return str(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError):
        return "0"
