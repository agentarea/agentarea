"""The currency every money amount this API returns is denominated in."""

from agentarea_common.auth.route_authz import unrestricted
from agentarea_common.extensions.customer_pricing import get_customer_pricing
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/pricing", tags=["pricing"])


class PricingCurrencyResponse(BaseModel):
    # ISO 4217. Costs, budgets and caps keep their ``*_usd`` field names for
    # compatibility, but hold amounts in this currency — the billing account's —
    # so a client has to read it here rather than assume dollars.
    currency: str


@router.get(
    "/currency",
    response_model=PricingCurrencyResponse,
    dependencies=[unrestricted("deployment-wide billing currency code; carries no workspace data")],
)
async def get_pricing_currency() -> PricingCurrencyResponse:
    """Return the billing currency of this deployment."""
    return PricingCurrencyResponse(currency=get_customer_pricing().currency())
