from decimal import Decimal, InvalidOperation

import pytest
from agentarea_common.money import Money, to_optional_money
from pydantic import BaseModel, ValidationError


class _Priced(BaseModel):
    amount: Money


def test_optional_money_keeps_unknown_apart_from_free():
    assert to_optional_money(None) is None
    assert to_optional_money(0) == Decimal("0")


def test_optional_money_reads_a_float_price_as_written():
    assert to_optional_money(1e-9) == Decimal("0.000000001")
    assert to_optional_money("0.000000123456") == Decimal("0.000000123456")


def test_optional_money_refuses_an_unparseable_price():
    with pytest.raises(InvalidOperation):
        to_optional_money("free")


@pytest.mark.parametrize("value", ["", "ten dollars", None])
def test_money_field_rejects_a_non_amount_as_a_validation_error(value):
    with pytest.raises(ValidationError):
        _Priced(amount=value)
