"""The deployment currency spend is counted in (wiki ADR-0038 §2.6)."""

from functools import cache

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from .base import BaseAppSettings


class SpendSettings(BaseAppSettings):
    """The one currency spend caps count and tool costs are declared in.

    The platform converts nothing: a cost in another currency is shown as not covered
    by caps. With billing installed, billing's ledger currency is the source of truth
    and this must name it, or the process refuses to start.
    """

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_SPEND_")

    CURRENCY: str = Field(default="USD", pattern=r"^[A-Z]{3}$")


@cache
def get_spend_currency() -> str:
    return SpendSettings().CURRENCY
