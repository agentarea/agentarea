"""The tenant boundary, enforced where every ORM query passes.

Workspace isolation used to depend on each query remembering
``_get_workspace_filter()``. This module moves the rule under the ORM: every
SELECT, bulk UPDATE and bulk DELETE a scoped session runs against a
:class:`WorkspaceScopedMixin` model is confined to the bound workspace:
reads by the model's :meth:`~WorkspaceScopedMixin.workspace_visibility`,
including relationship loads and joined entities, bulk writes strictly to the
workspace's own rows.

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
from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from ..config.database import TenantScopeMode
from .models import WorkspaceScopedMixin

logger = logging.getLogger(__name__)

_STACK_DEPTH = 6
_STDLIB = sysconfig.get_paths()["stdlib"]


class UnscopedQueryError(RuntimeError):
    """A workspace-scoped model was queried with no workspace scope and no bypass."""


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

    event.listen(session_class, "do_orm_execute", _confine)
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
    if scope is None:
        _unscoped_query(state, mode)
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


def _unscoped_query(state: ORMExecuteState, mode: TenantScopeMode) -> None:
    models = sorted(
        {m.class_.__name__ for m in state.all_mappers if issubclass(m.class_, WorkspaceScopedMixin)}
    )
    if not models:
        return
    frames = _application_frames()
    where = "".join(traceback.format_list(frames)) or "  <no application frames>\n"
    if mode is TenantScopeMode.ENFORCE:
        raise UnscopedQueryError(
            f"{', '.join(models)} queried with no workspace scope. Bind the workspace the "
            "work acts in (workspace_scope) or declare why it spans workspaces "
            f"(unscoped).\n{where}"
        )
    site = tuple((frame.filename, frame.lineno or 0) for frame in frames)
    if site in _reported_sites:
        return
    _reported_sites.add(site)
    logger.warning(
        "Unscoped ORM query on %s: no workspace scope is bound, so it ran unfiltered. "
        "AGENTAREA_DB_TENANT_SCOPE=enforce will refuse it.\n%s",
        ", ".join(models),
        where,
    )


def _application_frames() -> list[traceback.FrameSummary]:
    """The innermost frames of our own code that led to this query.

    Under ``AsyncSession`` the statement runs in a child greenlet whose stack
    ends inside SQLAlchemy; the awaiting coroutines are on the parent's.
    """
    frames: list[traceback.FrameSummary] = []
    parent = greenlet.getcurrent().parent
    outer: FrameType | None = parent.gr_frame if parent is not None else None
    if outer is not None:
        frames.extend(traceback.extract_stack(outer))
    frames.extend(traceback.extract_stack())
    ours = [
        frame
        for frame in frames
        if "site-packages" not in frame.filename
        and not frame.filename.startswith(_STDLIB)
        and frame.filename != __file__
    ]
    return ours[-_STACK_DEPTH:]
