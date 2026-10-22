"""What the account paying for a workspace has left to spend.

Additive extension point (see AGENTS.md → EXTENSION POINTS): an installed
``account_balance`` extension is active by being installed. Without one there is
no balance — a self-hosted install pays its providers directly.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from ..auth.context import UserContext
from .registry import ExtensionRegistry

ACCOUNT_BALANCE_EXTENSION = "account_balance"


@dataclass(frozen=True)
class AccountBalance:
    """The payer's balance as the caller may see it.

    ``amount`` is None when the caller is not the payer: they learn that runs are
    paid by someone else and whether that money ran out, never how much it is.
    """

    currency: str
    exhausted: bool
    viewer_is_payer: bool
    amount: Decimal | None


@runtime_checkable
class AccountBalanceSource(Protocol):
    async def balance(self, user_context: UserContext) -> AccountBalance:
        """Balance of the account paying for ``user_context.workspace_id``."""
        ...


class AccountBalanceUnavailableError(RuntimeError):
    """An installed account_balance extension could not be resolved."""


def get_account_balance_source() -> AccountBalanceSource | None:
    """The installed source, or None when this deployment has no balance at all."""
    factory = ExtensionRegistry.get_factory(ACCOUNT_BALANCE_EXTENSION)
    if factory is None:
        failure = ExtensionRegistry.get_failure(ACCOUNT_BALANCE_EXTENSION)
        if failure is not None:
            raise AccountBalanceUnavailableError(
                f"account_balance extension is installed but failed to load: {failure}"
            )
        return None
    source = factory()
    if not isinstance(source, AccountBalanceSource):
        kind = type(source).__name__
        raise AccountBalanceUnavailableError(
            f"account_balance extension returned {kind}, not an AccountBalanceSource"
        )
    return source
