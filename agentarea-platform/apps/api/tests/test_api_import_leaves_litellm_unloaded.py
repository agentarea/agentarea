"""Booting the API must not load litellm.

litellm adds ~240 MB of resident memory and ~2 s to every process that imports
it. The API reaches a model only on a few request paths, so the import belongs
to the first call, not to module load.
"""

import subprocess
import sys


def test_importing_the_api_app_does_not_load_litellm() -> None:
    probe = "import sys, agentarea_api.main; print('litellm' in sys.modules)"
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    assert result.stdout.strip().splitlines()[-1] == "False"
