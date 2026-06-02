"""Factory for building InterceptorRegistry and InterceptorPipeline."""

from __future__ import annotations

import logging

from agentarea_common.extensions.registry import ExtensionRegistry

from .domain.enums import Phase
from .engines.regex_engine import RegexDetectionEngine
from .interceptors.filters.mcp_tool_scanner import MCPToolSecurityScanner
from .interceptors.filters.output_sanitizer import OutputSanitizer
from .interceptors.filters.prompt_injection_detector import PromptInjectionDetector
from .interceptors.gates.capability_guard import CapabilityGuard
from .interceptors.gates.cost_budget_guard import CostBudgetGuard
from .interceptors.gates.semantic_guard import SemanticGuard
from .interceptors.gates.service_budget_guard import ServiceBudgetGuard
from .interceptors.gates.token_budget_guard import TokenBudgetGuard
from .interceptors.observers.audit_observer import AuditObserver
from .interceptors.observers.metrics_observer import MetricsObserver
from .pipeline import InterceptorPipeline
from .registry import InterceptorRegistry

logger = logging.getLogger(__name__)

# Priority convention:
#   100s — budget gates (run first, cheapest check)
#   120  — plan entitlement gate (enterprise only, injected via ExtensionRegistry)
#   200s — capability gates
#   300s — security filters
#   400s — advanced gates (semantic, escalation)
#   800s — observers (always last)


def create_governance_pipeline() -> InterceptorPipeline:
    """Create a fully configured pipeline with all v1 interceptors registered."""
    registry = InterceptorRegistry()
    engine = RegexDetectionEngine()

    # Budget gates
    registry.register(CostBudgetGuard(), Phase.PRE_LLM_CALL, priority=100)
    registry.register(CostBudgetGuard(), Phase.PRE_TOOL_CALL, priority=100)
    registry.register(TokenBudgetGuard(), Phase.PRE_LLM_CALL, priority=110)
    registry.register(ServiceBudgetGuard(), Phase.PRE_TOOL_CALL, priority=105)

    # Plan entitlement gate — enterprise only, injected via ExtensionRegistry
    if ExtensionRegistry.has("entitlement_guard"):
        entitlement_guard = ExtensionRegistry.get_factory("entitlement_guard")()
        registry.register(entitlement_guard, Phase.PRE_LLM_CALL, priority=120)
        logger.info("Plan entitlement guard registered (enterprise mode)")

    # Capability gate
    registry.register(CapabilityGuard(), Phase.PRE_TOOL_CALL, priority=200)
    registry.register(CapabilityGuard(), Phase.PRE_DELEGATION, priority=200)

    # Security filters — input
    registry.register(PromptInjectionDetector(engine), Phase.PRE_LLM_CALL, priority=300)

    # Security filters — output
    registry.register(OutputSanitizer(engine), Phase.POST_LLM_CALL, priority=300)
    registry.register(OutputSanitizer(engine), Phase.POST_TOOL_CALL, priority=300)

    # Tool discovery scanner
    registry.register(MCPToolSecurityScanner(engine), Phase.TOOL_DISCOVERY, priority=300)

    # Advanced gates
    registry.register(SemanticGuard(), Phase.PRE_TOOL_CALL, priority=400)
    # NOTE: human-approval escalation is NOT enforced here. The activity-boundary
    # interceptor cannot pause/resume a workflow, so an ESCALATE here would only
    # fail the activity. ApprovalPolicy is enforced inside the workflow loop
    # (policy_requires_approval -> HUMAN_APPROVAL_REQUESTED -> resolve_escalation),
    # which is the only place that can pause and wait for a human.

    # Observers (always last)
    metrics = MetricsObserver()
    audit = AuditObserver()
    for phase in Phase:
        registry.register(metrics, phase, priority=800)
        registry.register(audit, phase, priority=810)

    logger.info(
        "Governance pipeline created with %d interceptor registrations",
        _count_registrations(registry),
    )
    return InterceptorPipeline(registry)


def create_empty_pipeline() -> InterceptorPipeline:
    """Create a pipeline with empty registry (no-op pass-through)."""
    return InterceptorPipeline(InterceptorRegistry())


def _count_registrations(registry: InterceptorRegistry) -> int:
    return sum(len(registry.get_registrations(phase)) for phase in Phase)
