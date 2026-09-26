from decimal import Decimal

import pytest
from agentarea_common.money import Money
from pydantic import BaseModel, ValidationError


class _Budget(BaseModel):
    amount: Money


@pytest.mark.parametrize("raw", ["1.50", 1.5, 2, Decimal("0.01")])
def test_numeric_input_becomes_decimal(raw):
    assert _Budget(amount=raw).amount == Decimal(str(raw))


@pytest.mark.parametrize(
    "raw",
    [
        "ten dollars",
        "",
        {"a": 1},
        [1],
        "NaN",
        "Infinity",
        "-inf",
        True,
        # Decimal() reads every Unicode Nd digit; an amount is written in ASCII.
        "\u0e54\u0be7",
        "1\u0663.5",
        "\uff11\uff10",
    ],
)
def test_non_amounts_are_a_validation_error(raw):
    with pytest.raises(ValidationError):
        _Budget(amount=raw)


@pytest.mark.parametrize("raw", ["+1", "-2.5", ".5", "1.", "1e-9", "3E+2", " 4.20 "])
def test_ascii_decimal_notation_is_accepted(raw):
    assert _Budget(amount=raw).amount == Decimal(raw.strip())
