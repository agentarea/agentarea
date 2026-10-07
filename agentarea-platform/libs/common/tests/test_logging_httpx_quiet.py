"""httpx logs every request URL at INFO, query string and all.

A connection's secret query parameter (``?api_key=``, ``?ms=``) rides in that
URL under a name no redaction pattern can know, so the request log line itself
must stay below the level the services emit.
"""

import subprocess
import sys

_PROBE = """
import logging
from agentarea_common.logging import setup_logging

setup_logging(level="DEBUG")
for name in ("httpx", "httpcore"):
    print(logging.getLogger(name).getEffectiveLevel())
"""


def test_setup_logging_keeps_httpx_request_lines_out_even_at_debug():
    out = subprocess.run(
        [sys.executable, "-c", _PROBE], capture_output=True, text=True, check=True
    ).stdout.split()

    assert [int(level) for level in out] == [30, 30]
