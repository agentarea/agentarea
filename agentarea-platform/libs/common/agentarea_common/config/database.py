"""Database configuration and connection management.

Single source of truth for SQLAlchemy engines and sessions. There is exactly
one ``Database`` instance per process, owning:

* ``engine`` / ``async_session_factory`` — primary async (write) connections,
  transactional.
* ``read_engine`` / ``read_session_factory`` — read-replica async connections
  (AUTOCOMMIT; falls back to the primary host when no replica is configured).
* ``sync_engine`` / ``sync_session_factory`` — synchronous connections, used by
  Alembic migrations.

All pools share the same liveness/recycle policy so the configuration cannot
drift between engines.
"""

import logging
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from enum import StrEnum
from functools import lru_cache
from typing import Any, Optional

from pydantic_settings import SettingsConfigDict
from sqlalchemy import URL, Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from .base import BaseAppSettings

logger = logging.getLogger(__name__)


class DatabaseSettings(BaseAppSettings):
    """Database configuration and connection settings.

    ``POSTGRES_*`` stays the contract of the postgres image itself ("create this
    user and database"); what our services read to connect is separate, and
    prefixed. The pool knobs used to be bare ``POOL_SIZE`` / ``MAX_OVERFLOW`` /
    ``ECHO``, generic enough to collide with anything else in the environment.
    """

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_DB_")

    USER: str = "postgres"
    PASSWORD: str = "postgres"  # noqa: S105
    HOST: str = "db"
    PORT: str = "5432"
    NAME: str = "agentarea"
    # libpq sslmode (disable, prefer, require, verify-ca, verify-full); unset
    # leaves each driver on its own default.
    SSLMODE: str | None = None
    POOL_SIZE: int = 20  # Increased from 5 to handle more concurrent SSE connections
    POOL_OVERFLOW: int = 30  # Increased from 10 to handle bursts
    POOL_TIMEOUT: int = 30  # Timeout for getting connection from pool
    POOL_RECYCLE: int = 3600  # Recycle connections every hour to prevent stale connections
    ECHO: bool = False
    READ_HOST: str | None = None
    READ_PORT: int | None = None
    READ_POOL_SIZE: int = 15
    READ_POOL_OVERFLOW: int = 20

    def _url(self, driver: str, host: str, port: str | int, ssl_param: str) -> URL:
        return URL.create(
            driver,
            username=self.USER,
            password=self.PASSWORD,
            host=host,
            port=int(port),
            database=self.NAME,
            query={ssl_param: self.SSLMODE} if self.SSLMODE else {},
        )

    @property
    def read_url(self) -> URL:
        """Async database URL for the read replica (falls back to primary if not configured)."""
        return self._url(
            "postgresql+asyncpg", self.READ_HOST or self.HOST, self.READ_PORT or self.PORT, "ssl"
        )

    @property
    def url(self) -> URL:
        """Async database URL for SQLAlchemy."""
        # asyncpg takes the libpq sslmode values under the name ``ssl``.
        return self._url("postgresql+asyncpg", self.HOST, self.PORT, "ssl")

    @property
    def sync_url(self) -> URL:
        """Sync database URL for SQLAlchemy."""
        return self._url("postgresql", self.HOST, self.PORT, "sslmode")


class TenantScopeMode(StrEnum):
    """What a query on a workspace-scoped model does when no workspace is bound."""

    LOG = "log"
    ENFORCE = "enforce"


class TenantScopeSettings(BaseAppSettings):
    """How the ORM treats a workspace-scoped query that names no workspace.

    Required, with no default: ``log`` runs it unfiltered and warns, ``enforce``
    refuses it. Kept apart from :class:`DatabaseSettings` because migrations
    read those and never open an ORM session.
    """

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_DB_")

    TENANT_SCOPE: TenantScopeMode

    # Pydantic Settings may populate required fields from the environment.
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)


class Database:
    """Database connection manager using singleton pattern."""

    _instance: Optional["Database"] = None
    _initialized: bool = False

    def __init__(self, settings: DatabaseSettings | None = None) -> None:
        """Initialize database connections."""
        if self._initialized:
            return

        self.settings = settings or get_db_settings()
        self._setup_engines()
        self._setup_session_factories()
        self._initialized = True

    @classmethod
    def get_instance(cls, settings: DatabaseSettings | None = None) -> "Database":
        """Get the singleton instance of Database."""
        if cls._instance is None:
            instance = cls.__new__(cls)
            instance.__init__(settings)
            cls._instance = instance
        return cls._instance

    def _setup_engines(self) -> None:
        """Setup async (write + read) and sync database engines.

        ``pool_pre_ping`` verifies a pooled connection is still alive on checkout
        and transparently reconnects if the server closed it. Without it, a
        connection reaped server-side (idle timeout, restart, PgBouncer) is
        handed out dead and asyncpg raises "the underlying connection is closed".
        """
        # Shared liveness/recycle policy applied to every engine so pool
        # configuration cannot drift between write, read, and sync engines.
        pool_kwargs = {
            "echo": self.settings.ECHO,
            "pool_pre_ping": True,
            "pool_recycle": self.settings.POOL_RECYCLE,
            "pool_timeout": self.settings.POOL_TIMEOUT,
        }

        self.engine: AsyncEngine = create_async_engine(
            self.settings.url,
            pool_size=self.settings.POOL_SIZE,
            max_overflow=self.settings.POOL_OVERFLOW,
            **pool_kwargs,
        )
        self.sync_engine: Engine = create_engine(
            self.settings.sync_url,
            pool_size=self.settings.POOL_SIZE,
            max_overflow=self.settings.POOL_OVERFLOW,
            **pool_kwargs,
        )

        if self.settings.READ_HOST:
            # A read replica is configured: give it its own connection pool to
            # the replica host, sized independently and running in AUTOCOMMIT.
            self.read_engine: AsyncEngine = create_async_engine(
                self.settings.read_url,
                pool_size=self.settings.READ_POOL_SIZE,
                max_overflow=self.settings.READ_POOL_OVERFLOW,
                execution_options={"isolation_level": "AUTOCOMMIT"},
                **pool_kwargs,
            )
        else:
            # No replica: read_url is the primary, so opening a second pool to
            # the same Postgres just duplicates connections in every process
            # (notably the Temporal worker, which never opens read sessions).
            # Reuse the write engine's pool via a lightweight execution-options
            # variant — reads still run in AUTOCOMMIT (no transactions), they
            # just share the primary's connections.
            self.read_engine = self.engine.execution_options(isolation_level="AUTOCOMMIT")

    def _setup_session_factories(self) -> None:
        """Setup session factories for async (write/read) and sync sessions.

        Both async factories confine workspace-scoped models to the bound
        workspace (see ``agentarea_common.base.tenant_scope``).
        """
        from ..base.tenant_scope import tenant_scoped_session_class

        scoped_session_class = tenant_scoped_session_class(get_tenant_scope_settings().TENANT_SCOPE)
        self.async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            sync_session_class=scoped_session_class,
            expire_on_commit=False,
        )
        self.read_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.read_engine,
            class_=AsyncSession,
            sync_session_class=scoped_session_class,
            expire_on_commit=False,
        )
        self.sync_session_factory: sessionmaker[Session] = sessionmaker(
            self.sync_engine,
            expire_on_commit=False,
        )

    # Backwards-compatible alias for callers that used the read/write-split
    # module's ``db.session_factory``.
    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self.async_session_factory

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get an async (write) database session with transaction management."""
        session = self.async_session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    # ``get_db`` is the historical name for the transactional write session
    # context manager; keep it as an alias of ``session``.
    get_db = session

    @asynccontextmanager
    async def read_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a read-only database session (AUTOCOMMIT — no transaction management)."""
        session = self.read_session_factory()
        try:
            yield session
        finally:
            try:
                await session.close()
            except Exception as exc:
                logger.debug("Failed to close read DB session cleanly: %s", exc)

    @contextmanager
    def get_sync_db(self) -> Generator[Session, None, None]:
        """Get a synchronous database session - used for migrations."""
        session = self.sync_session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


@lru_cache
def get_db_settings() -> DatabaseSettings:
    """Get database settings."""
    return DatabaseSettings()


@lru_cache
def get_tenant_scope_settings() -> TenantScopeSettings:
    """Get the tenant scope enforcement settings."""
    return TenantScopeSettings()


# Global database instance - initialized lazily so importing this module does
# not build engines (and read AGENTAREA_DB_* env) at import time.
_db_instance: Database | None = None


def get_database() -> Database:
    """Get the global database instance, creating it if necessary."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database.get_instance()
    return _db_instance


def get_db():
    """Get an async (write) database session context manager."""
    return get_database().get_db()


def get_sync_db():
    """Get a synchronous database session."""
    return get_database().get_sync_db()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for an async (write) database session.

    Flat async-generator form (commit/rollback/close) so ``session.close()``
    still runs when the client disconnects mid-response and FastAPI cancels the
    generator.
    """
    async with get_database().session() as session:
        yield session


async def get_read_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for a read-only (AUTOCOMMIT) database session."""
    async with get_database().read_session() as session:
        yield session


def __getattr__(name: str) -> object:
    """Lazily resolve the module-level ``db`` singleton (PEP 562).

    Lets ``from agentarea_common.config.database import db`` work without
    building engines at import time of this module.
    """
    if name == "db":
        return get_database()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
