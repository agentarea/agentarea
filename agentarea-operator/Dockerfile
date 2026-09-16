FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Installed from pyproject.toml, not a hand-written list.
#
# The list used to be written out here as well, and the two drifted: the declared
# dependencies gained pins that never reached the image, and adding one to
# pyproject.toml changed nothing that ships. That failure is silent until the import
# runs in the cluster — the tests pass locally, because locally the package is
# installed from the file this ignored.
COPY pyproject.toml ./
COPY handler.py registry_sync.py ./
RUN pip install --no-cache-dir .

CMD ["kopf", "run", "handler.py", "--verbose"]
