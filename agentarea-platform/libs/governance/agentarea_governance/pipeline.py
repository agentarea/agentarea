"""Interceptor pipeline — chain of responsibility execution.

Infrastructure-agnostic. Handles gates, filters, and observers differently
based on their category.
"""

from __future__ import annotations

import logging
from typing import Any

from .domain.enums import InterceptorAction, InterceptorCategory, Phase
from .domain.models import InterceptorContext, InterceptorResult
from .registry import InterceptorRegistry

logger = logging.getLogger(__name__)


class InterceptorPipeline:
    """Executes registered interceptors per phase in priority order."""

    def __init__(self, registry: InterceptorRegistry) -> None:
        self._registry = registry

    async def run(self, phase: Phase, context: InterceptorContext) -> InterceptorResult:
        if not self._registry.has_interceptors(phase):
            return InterceptorResult(
                action=InterceptorAction.ALLOW,
                interceptor_name="pipeline",
                reason="no interceptors registered",
            )

        registrations = self._registry.get_registrations(phase)
        original_content = context.content
        current_content = context.content

        for registration in registrations:
            interceptor = registration.interceptor
            category = interceptor.category

            if category == InterceptorCategory.OBSERVER:
                await self._run_observer(interceptor, context)
                continue

            try:
                result = await interceptor.execute(context)
            except Exception as exc:
                logger.exception(
                    "Interceptor %s raised exception on phase %s",
                    interceptor.name,
                    phase.value,
                )
                # GATE and FILTER interceptors are security-relevant (both can DENY
                # on success — see e.g. PromptInjectionDetector). An exception must
                # fail closed rather than silently fall through to ALLOW.
                deny_result = InterceptorResult(
                    action=InterceptorAction.DENY,
                    interceptor_name=interceptor.name,
                    reason=(
                        f"{category.value} interceptor '{interceptor.name}' raised "
                        f"{exc.__class__.__name__} during execution; failing closed "
                        "(this is an error, not a policy decision)"
                    ),
                )
                await self._fire_callback(registration.on_deny, deny_result, context)
                return deny_result

            if category == InterceptorCategory.GATE:
                if result.action == InterceptorAction.DENY:
                    await self._fire_callback(registration.on_deny, result, context)
                    return result
                if result.action == InterceptorAction.ESCALATE:
                    await self._fire_callback(registration.on_escalate, result, context)
                    return result
                if result.action == InterceptorAction.WARN:
                    await self._fire_callback(registration.on_warn, result, context)

            elif category == InterceptorCategory.FILTER:
                if result.action == InterceptorAction.DENY:
                    await self._fire_callback(registration.on_deny, result, context)
                    return result
                if (
                    result.action == InterceptorAction.MODIFY
                    and result.modified_content is not None
                ):
                    current_content = result.modified_content
                    context = InterceptorContext(
                        agent_id=context.agent_id,
                        workspace_id=context.workspace_id,
                        user_id=context.user_id,
                        phase=context.phase,
                        action_type=context.action_type,
                        action_name=context.action_name,
                        action_params=context.action_params,
                        content=current_content,
                        execution_state=context.execution_state,
                    )
                if result.action == InterceptorAction.WARN:
                    await self._fire_callback(registration.on_warn, result, context)

        if current_content != original_content and current_content is not None:
            return InterceptorResult(
                action=InterceptorAction.MODIFY,
                interceptor_name="pipeline",
                reason="content modified by filters",
                modified_content=current_content,
            )

        return InterceptorResult(
            action=InterceptorAction.ALLOW,
            interceptor_name="pipeline",
            reason="all checks passed",
        )

    async def _run_observer(self, interceptor: Any, context: InterceptorContext) -> None:
        try:
            await interceptor.execute(context)
        except Exception:
            logger.exception("Observer %s raised exception (ignored)", interceptor.name)

    async def _fire_callback(
        self,
        callback: Any,
        result: InterceptorResult,
        context: InterceptorContext,
    ) -> None:
        if callback is None:
            return
        try:
            ret = callback(result, context)
            if hasattr(ret, "__await__"):
                await ret
        except Exception:
            logger.exception("Callback raised exception (ignored)")
