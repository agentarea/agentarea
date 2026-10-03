"""Suites and cases: what an agent revision is tested against."""

from typing import Any
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_tasks.infrastructure.orm import TaskConversationEntryORM, TaskORM
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_evals.models import EvalCase, EvalSuite
from agentarea_evals.suites.checks import validate_checks

# Per-run resource overrides change what runs; a case tests the revision as it is.
RUN_OVERRIDE_KEYS = ("model_override", "mcps", "mcp", "mcp_servers", "skills")
# Bookkeeping a run carries about where it came from, not input.
_PROVENANCE_KEYS = ("source", "parent_agent_id", "parent_task_id", "channel_origin")


class SuiteError(ValueError):
    pass


class SuiteService:
    def __init__(self, session: AsyncSession, user_context: UserContext):
        self.session = session
        self.user_context = user_context

    def _scoped(self, model: Any) -> Any:
        return model.workspace_id == self.user_context.workspace_id

    async def create_suite(self, name: str, description: str | None) -> EvalSuite:
        suite = EvalSuite(
            name=name,
            description=description,
            workspace_id=self.user_context.workspace_id,
            created_by=self.user_context.user_id,
        )
        self.session.add(suite)
        await self.session.commit()
        return suite

    async def list_suites(self) -> list[EvalSuite]:
        result = await self.session.execute(
            select(EvalSuite).where(self._scoped(EvalSuite)).order_by(EvalSuite.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_suite(self, suite_id: UUID) -> EvalSuite | None:
        result = await self.session.execute(
            select(EvalSuite).where(EvalSuite.id == suite_id, self._scoped(EvalSuite))
        )
        return result.scalar_one_or_none()

    async def update_suite(
        self, suite_id: UUID, *, name: str, description: str | None
    ) -> EvalSuite:
        suite = await self._require_suite(suite_id)
        suite.name = name
        suite.description = description
        await self.session.commit()
        return suite

    async def delete_suite(self, suite_id: UUID) -> None:
        suite = await self._require_suite(suite_id)
        await self.session.delete(suite)
        await self.session.commit()

    async def list_cases(self, suite_id: UUID) -> list[EvalCase]:
        result = await self.session.execute(
            select(EvalCase)
            .where(EvalCase.suite_id == suite_id, self._scoped(EvalCase))
            .order_by(EvalCase.created_at)
        )
        return list(result.scalars().all())

    async def get_case(self, case_id: UUID) -> EvalCase | None:
        result = await self.session.execute(
            select(EvalCase).where(EvalCase.id == case_id, self._scoped(EvalCase))
        )
        return result.scalar_one_or_none()

    async def add_case(
        self,
        suite_id: UUID,
        *,
        name: str,
        input: str,
        parameters: dict[str, Any],
        checks: list[dict[str, Any]],
        stubs: dict[str, Any],
        source_task_id: UUID | None = None,
    ) -> EvalCase:
        await self._require_suite(suite_id)
        case = EvalCase(
            suite_id=suite_id,
            name=name,
            input=input,
            parameters=self._case_parameters(parameters),
            checks=validate_checks(checks),
            stubs=dict(stubs),
            source_task_id=source_task_id,
            workspace_id=self.user_context.workspace_id,
            created_by=self.user_context.user_id,
        )
        self.session.add(case)
        await self.session.commit()
        return case

    async def update_case(
        self,
        case_id: UUID,
        *,
        name: str,
        input: str,
        parameters: dict[str, Any],
        checks: list[dict[str, Any]],
        stubs: dict[str, Any],
    ) -> EvalCase:
        case = await self.get_case(case_id)
        if case is None:
            raise SuiteError(f"case {case_id} not found")
        case.name = name
        case.input = input
        case.parameters = self._case_parameters(parameters)
        case.checks = validate_checks(checks)
        case.stubs = dict(stubs)
        await self.session.commit()
        return case

    async def delete_case(self, case_id: UUID) -> None:
        case = await self.get_case(case_id)
        if case is None:
            raise SuiteError(f"case {case_id} not found")
        await self.session.delete(case)
        await self.session.commit()

    async def case_from_task(
        self, suite_id: UUID, task_id: UUID, *, name: str | None = None
    ) -> EvalCase:
        """A case built from a real run: its input, and stubs from its tool answers.

        The stubs are drafts the author confirms; checks start empty, so the
        harvested case asks only that the run completes.
        """
        task = (
            await self.session.execute(
                select(TaskORM).where(TaskORM.id == task_id, self._scoped(TaskORM))
            )
        ).scalar_one_or_none()
        if task is None:
            raise SuiteError(f"run {task_id} not found")
        parameters = {
            key: value
            for key, value in (task.parameters or {}).items()
            if key not in RUN_OVERRIDE_KEYS and key not in _PROVENANCE_KEYS
        }
        return await self.add_case(
            suite_id,
            name=name or (task.description or "")[:200] or str(task_id),
            input=task.description,
            parameters=parameters,
            checks=[],
            stubs=await self._recorded_tool_answers(task_id),
            source_task_id=task_id,
        )

    async def _recorded_tool_answers(self, task_id: UUID) -> dict[str, Any]:
        entries = (
            await self.session.execute(
                select(TaskConversationEntryORM)
                .where(
                    TaskConversationEntryORM.task_id == task_id,
                    self._scoped(TaskConversationEntryORM),
                )
                .order_by(TaskConversationEntryORM.seq)
            )
        ).scalars()
        names: dict[str, str] = {}
        answers: dict[str, Any] = {}
        for entry in entries:
            for call in entry.tool_calls or []:
                function = call.get("function") or {}
                if call.get("id") and (function.get("name") or call.get("name")):
                    names[call["id"]] = function.get("name") or call["name"]
            if entry.role == "tool":
                tool = entry.name or names.get(entry.tool_call_id or "")
                if tool and tool not in answers:
                    answers[tool] = entry.content
        return answers

    async def _require_suite(self, suite_id: UUID) -> EvalSuite:
        suite = await self.get_suite(suite_id)
        if suite is None:
            raise SuiteError(f"suite {suite_id} not found")
        return suite

    @staticmethod
    def _case_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
        overrides = sorted(key for key in parameters if key in RUN_OVERRIDE_KEYS)
        if overrides:
            raise SuiteError(
                f"a case tests the revision as it is; remove the run overrides {overrides}"
            )
        return dict(parameters)
