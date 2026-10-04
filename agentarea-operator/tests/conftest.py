import os

# handler.py builds its engine at import time from the same AGENTAREA_DB_*
# variables every service reads. Unit tests never connect, so placeholders do.
for name, value in {
    "AGENTAREA_DB_USER": "operator-test",
    "AGENTAREA_DB_PASSWORD": "operator-test",  # pragma: allowlist secret
    "AGENTAREA_DB_HOST": "localhost",
    "AGENTAREA_DB_NAME": "agentarea",
}.items():
    os.environ.setdefault(name, value)
