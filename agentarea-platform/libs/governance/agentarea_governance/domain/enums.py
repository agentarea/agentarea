"""Enums for the interceptor framework."""

from enum import StrEnum


class InterceptorCategory(StrEnum):
    """How the pipeline executes this interceptor."""

    GATE = "gate"
    FILTER = "filter"
    OBSERVER = "observer"


class Phase(StrEnum):
    """Execution boundary where interceptors run."""

    PRE_LLM_CALL = "pre_llm_call"
    POST_LLM_CALL = "post_llm_call"
    PRE_TOOL_CALL = "pre_tool_call"
    POST_TOOL_CALL = "post_tool_call"
    PRE_DELEGATION = "pre_delegation"
    POST_DELEGATION = "post_delegation"
    TOOL_DISCOVERY = "tool_discovery"


class InterceptorAction(StrEnum):
    """Decision returned by an interceptor."""

    ALLOW = "allow"
    DENY = "deny"
    WARN = "warn"
    ESCALATE = "escalate"
    MODIFY = "modify"
