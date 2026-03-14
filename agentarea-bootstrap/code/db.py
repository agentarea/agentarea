"""Shared database connection for all bootstrap scripts.

Supports two modes:
  1. DATABASE_URL env var (explicit connection string)
  2. Individual POSTGRES_* env vars (builds URL from parts)

This is the single source of truth for DB connection in bootstrap.
"""

import os
from urllib.parse import quote_plus

from sqlalchemy import create_engine


def get_database_url() -> str:
    """Build PostgreSQL connection URL from env vars."""
    explicit = os.environ.get("DATABASE_URL")
    if explicit:
        return explicit

    user = os.environ.get("POSTGRES_USER", "user")
    password = os.environ.get("POSTGRES_PASSWORD", "password")
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "agentarea")
    sslmode = os.environ.get("PGSSLMODE", "")

    url = f"postgresql+psycopg2://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{db}"
    if sslmode:
        url += f"?sslmode={sslmode}"
    return url


engine = create_engine(get_database_url(), pool_pre_ping=True)
