FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir kopf kubernetes sqlalchemy psycopg2-binary httpx pyyaml

COPY handler.py registry_sync.py ./

CMD ["kopf", "run", "handler.py", "--verbose"]
