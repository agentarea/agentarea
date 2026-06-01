"""Domain exceptions for the tasks library."""


class BudgetCapExceededError(Exception):
    """Raised when a workspace's month-to-date spend has reached its monthly cap.

    Maps to HTTP 402 Payment Required at the API boundary. The numeric
    fields are surfaced in the response body so the UI can render an
    actionable message ("you've spent $X of $Y, raise the cap or wait
    until next month").
    """

    def __init__(self, *, workspace_id: str, current_mtd_usd: float, cap_usd: float):
        self.workspace_id = workspace_id
        self.current_mtd_usd = current_mtd_usd
        self.cap_usd = cap_usd
        super().__init__(
            f"Workspace {workspace_id} MTD spend ${current_mtd_usd:.2f} "
            f"has reached cap ${cap_usd:.2f}"
        )
