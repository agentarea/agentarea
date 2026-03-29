"""Domain exceptions for the wallet module."""


class WalletAlreadyExistsError(Exception):
    """Raised when a wallet already exists for the given agent."""


class WalletNotFoundError(Exception):
    """Raised when a wallet is not found for the given agent."""


class InsufficientBudgetError(Exception):
    """Raised when an agent does not have enough budget to make a payment."""


class UnsupportedProtocolError(Exception):
    """Raised when a payment protocol is not supported by the wallet."""
