"""Unified money type for consistent monetary value handling.

All monetary values across the platform should use this type:
- Money — Decimal with Pydantic str serialization. Use for model fields, arithmetic, everything.
- to_money() — safe constructor from any numeric input
- serialize_money() — for dict/event contexts that bypass Pydantic
"""

from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import BeforeValidator, PlainSerializer

# Single money type: Decimal internally, serializes to str in Pydantic JSON.
# Use for all monetary fields — model fields, function args, internal storage.
Money = Annotated[
    Decimal,
    BeforeValidator(lambda v: Decimal(str(v)) if not isinstance(v, Decimal) else v),
    PlainSerializer(lambda v: str(v), return_type=str),
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
