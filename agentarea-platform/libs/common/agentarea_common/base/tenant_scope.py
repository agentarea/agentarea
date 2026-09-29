"""The tenant boundary, enforced where every ORM query passes.

Workspace isolation used to depend on each query remembering
``_get_workspace_filter()``. This module moves the rule under the ORM: every
SELECT, bulk UPDATE and bulk DELETE a scoped session runs against a
:class:`WorkspaceScopedMixin` model is confined to the bound workspace:
reads by the model's :meth:`~WorkspaceScopedMixin.workspace_visibility`,
including relationship loads and joined entities, bulk writes strictly to the
workspace's own rows. A flush writes only rows of the bound workspace, and a
Core statement on a scoped table, which the scope cannot confine, is treated
like a query with no scope.

The workspace comes from a contextvar, bound where a request or activity learns
which workspace it acts in (:func:`bind_workspace_scope`,
:func:`workspace_scope`). Work that legitimately spans workspaces says so with
:func:`unscoped`, and the reason is required. A scoped query with neither is a
bug: ``log`` mode lets it through unfiltered and warns once per call site,
``enforce`` mode raises :class:`UnscopedQueryError`.

This is the tenant boundary only. Who may do what inside a workspace is still
decided by the ReBAC graph.
"""

from __future__ import annotations

import logging
import sysconfig
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from types import FrameType

import greenlet
from sqlalchemy import event, inspect
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria
from sqlalchemy.sql import visitors
from sqlalchemy.sql.expression import ClauseElement, Executable, TableClause

from ..config.database import TenantScopeMode
from .models import WorkspaceScopedMixin

logger = logging.getLogger(__name__)

_STACK_DEPTH = 6
_STDLIB = sysconfig.get_paths()["stdlib"]


class UnscopedQueryError(RuntimeError):
    """A workspace-scoped table was reached outside the bound workspace and with no bypass."""


@dataclass(frozen=True)
class _Bypass:
    reason: str


_scope: ContextVar[str | _Bypass | None] = ContextVar("tenant_scope", default=None)
_reported_sites: set[tuple[tuple[str, int], ...]] = set()


def current_workspace_scope() -> str | None:
    """The workspace ORM queries are confined to, or None when there is none."""
    scope = _scope.get()
    return scope if isinstance(scope, str) else None


def bind_workspace_scope(workspace_id: str) -> None:
    """Confine the rest of the current task to ``workspace_id``.

    For a request dependency or an activity, which run in a task of their own
    and learn their workspace partway through; everywhere else prefer
    :func:`workspace_scope`.
    """
    _scope.set(_require_workspace(workspace_id))


@contextmanager
def workspace_scope(workspace_id: str) -> Iterator[None]:
    """Confine ORM queries in the block to ``workspace_id``."""
    token = _scope.set(_require_workspace(workspace_id))
    try:
        yield
    finally:
        _scope.reset(token)


@contextmanager
def unscoped(reason: str) -> Iterator[None]:
    """Run the block across every workspace. ``reason`` says why that is right."""
    if not reason or not reason.strip():
        raise ValueError("unscoped() needs a reason: say why this work spans workspaces")
    token = _scope.set(_Bypass(reason))
    try:
        yield
    finally:
        _scope.reset(token)


def tenant_scoped_session_class(mode: TenantScopeMode) -> type[Session]:
    """A ``Session`` class whose ORM statements are confined to the current workspace."""
    session_class = type("TenantScopedSession", (Session,), {})

    def _confine(state: ORMExecuteState) -> None:
        _confine_statement(state, mode)

    def _check_flush(session: Session, _flush_context: object, _instances: object) -> None:
        _check_flush_ownership(session, mode)

    event.listen(session_class, "do_orm_execute", _confine)
    event.listen(session_class, "before_flush", _check_flush)
    return session_class


def _require_workspace(workspace_id: str) -> str:
    if not workspace_id:
        raise ValueError("a workspace scope needs a workspace id")
    return workspace_id


def _confine_statement(state: ORMExecuteState, mode: TenantScopeMode) -> None:
    # A column load re-reads a row this session already holds, by primary key.
    if state.is_column_load or not (state.is_select or state.is_update or state.is_delete):
        return
    scope = _scope.get()
    if isinstance(scope, _Bypass):
        return
    models = sorted(
        {m.class_.__name__ for m in state.all_mappers if issubclass(m.class_, WorkspaceScopedMixin)}
    )
    if not models:
        models, tables = _scoped_references(state.statement)
        if tables and not models:
            _report(
                mode,
                f"Core statement on workspace-scoped {', '.join(tables)}: no workspace scope "
                "can confine it. Go through the ORM entity or declare why it spans "
                "workspaces (unscoped).",
            )
            return
        if not models:
            return
    if scope is None:
        _report(
            mode,
            f"Unscoped ORM query on {', '.join(models)}: no workspace scope is bound. Bind "
            "the workspace the work acts in (workspace_scope) or declare why it spans "
            "workspaces (unscoped).",
        )
        return
    workspace_id = scope
    if state.is_select:
        criteria = with_loader_criteria(
            WorkspaceScopedMixin,
            lambda cls: cls.workspace_visibility(workspace_id),
            include_aliases=True,
        )
    else:
        # Rows another workspace may read are still not this one's to change.
        criteria = with_loader_criteria(
            WorkspaceScopedMixin,
            lambda cls: cls.workspace_id == workspace_id,
            include_aliases=True,
        )
    state.statement = state.statement.options(criteria)


def _scoped_references(statement: Executable) -> tuple[list[str], list[str]]:
    """Scoped ORM entities anywhere in ``statement``, and the scoped tables it names."""
    entities: set[str] = set()
    names: set[str] = set()
    if not isinstance(statement, ClauseElement):
        return [], []
    for element in visitors.iterate(statement):
        entity = getattr(element, "_annotations", {}).get("parententity")
        if entity is not None and issubclass(entity.class_, WorkspaceScopedMixin):
            entities.add(entity.class_.__name__)
        elif isinstance(element, TableClause):
            names.add(element.name)
    tables = sorted(names & _scoped_table_names()) if names else []
    return sorted(entities), tables


def _scoped_table_names() -> set[str]:
    names: set[str] = set()
    pending = list(WorkspaceScopedMixin.__subclasses__())
    while pending:
        cls = pending.pop()
        pending.extend(cls.__subclasses__())
        mapper = inspect(cls, raiseerr=False)
        if mapper is not None:
            names.update(table.name for table in mapper.tables)
    return names


def _check_flush_ownership(session: Session, mode: TenantScopeMode) -> None:
    scope = _scope.get()
    if isinstance(scope, _Bypass):
        return
    written = [
        obj
        for obj in (*session.new, *session.dirty, *session.deleted)
        if isinstance(obj, WorkspaceScopedMixin)
    ]
    if scope is None:
        models = sorted({type(obj).__name__ for obj in written})
        if models:
            _report(
                mode,
                f"Unscoped flush of {', '.join(models)}: no workspace scope is bound. Bind "
                "the workspace the work acts in (workspace_scope) or declare why it spans "
                "workspaces (unscoped).",
            )
        return
    foreign = sorted(
        {
            f"{type(obj).__name__} of {obj.workspace_id!r}"
            for obj in written
            if obj.workspace_id != scope
        }
    )
    if foreign:
        _report(
            mode,
            f"Flush from workspace {scope!r} writes {', '.join(foreign)}: a workspace writes "
            "only its own rows. Work that spans workspaces declares why (unscoped).",
        )


def _report(mode: TenantScopeMode, problem: str) -> None:
    frames = _application_frames()
    if mode is TenantScopeMode.ENFORCE:
        raise UnscopedQueryError(f"{problem}\n{_format(frames)}")
    site = tuple((frame.f_code.co_filename, lineno) for frame, lineno in frames)
    if site in _reported_sites:
        return
    _reported_sites.add(site)
    logger.warning(
        "%s AGENTAREA_DB_TENANT_SCOPE=enforce will refuse it.\n%s", problem, _format(frames)
    )


def _format(frames: list[tuple[FrameType, int]]) -> str:
    summary = traceback.StackSummary.extract(reversed(frames))
    return "".join(summary.format()) or "  <no application frames>\n"


def _application_frames() -> list[tuple[FrameType, int]]:
    """The innermost frames of our own code that led here, innermost first.

    Under ``AsyncSession`` the statement runs in a child greenlet whose stack
    ends inside SQLAlchemy; the awaiting coroutines are on the parent's. Only
    frame objects are collected; source lines are read when a report is written.
    """
    parent = greenlet.getcurrent().parent
    outer: FrameType | None = parent.gr_frame if parent is not None else None
    frames = list(traceback.walk_stack(None))
    if outer is not None:
        frames.extend(traceback.walk_stack(outer))
    ours = [
        (frame, lineno) for frame, lineno in frames if _is_application(frame.f_code.co_filename)
    ]
    return ours[:_STACK_DEPTH]


def _is_application(filename: str) -> bool:
    return (
        "site-packages" not in filename
        and not filename.startswith((_STDLIB, "<frozen "))
        and filename != __file__
    )
