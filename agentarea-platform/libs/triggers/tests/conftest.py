import sys
from unittest.mock import MagicMock

# Mock temporalio if not present
if "temporalio" not in sys.modules:
    temporalio_mock = MagicMock()
    sys.modules["temporalio"] = temporalio_mock
    sys.modules["temporalio.client"] = MagicMock()
    sys.modules["temporalio.worker"] = MagicMock()
    sys.modules["temporalio.activity"] = MagicMock()
    sys.modules["temporalio.workflow"] = MagicMock()
    sys.modules["temporalio.api"] = MagicMock()
    sys.modules["temporalio.api.common"] = MagicMock()
    sys.modules["temporalio.api.common.v1"] = MagicMock()
    sys.modules["temporalio.common"] = MagicMock()
    sys.modules["temporalio.exceptions"] = MagicMock()
    sys.modules["temporalio.service"] = MagicMock()
