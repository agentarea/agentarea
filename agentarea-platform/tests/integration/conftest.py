"""Integration-test collection config.

Applies external-dependency gate markers by test-file name so the marks live
in one place instead of being sprinkled across ~20 modules. The core CI job
runs `-m "not requires_llm and not requires_docker and not requires_server and
not requires_s3 and not perf"`; a separate opt-in job runs the gated ones.
"""

import pytest

# file stem (without .py) -> gate marker
_GATE_MARKERS: dict[str, str] = {
    # need a real LLM endpoint (Ollama/OpenRouter)
    "test_full_workflow_with_real_llm": "requires_llm",
    "test_real_llm_simple": "requires_llm",
    "test_real_llm_tool_calls": "requires_llm",
    "test_real_llm_with_mocked_db": "requires_llm",
    "test_real_completion_tool": "requires_llm",
    "test_malformed_llm_responses": "requires_llm",
    "test_react_framework_behavior": "requires_llm",
    "test_llm_response_parser": "requires_llm",
    "test_real_workflow_infrastructure": "requires_llm",
    "test_real_workflow_with_mocked_db": "requires_llm",
    "test_sdk_temporal_integration": "requires_llm",
    "test_a2a_task_execution_comprehensive": "requires_llm",
    # need object storage
    "test_artifact_service": "requires_s3",
    # need Docker / live MCP containers
    "test_mcp_containerization": "requires_docker",
    "test_mcp_real_integration": "requires_docker",
    "test_agent_mcp_e2e": "requires_docker",
    # need a running API server
    "test_e2e_main_flow": "requires_server",
    "test_protocol_endpoints": "requires_server",
    "test_a2a_real_api": "requires_server",
    "test_agent_delegation_e2e": "requires_server",
    # timing-sensitive stress test
    "test_trigger_performance_concurrent": "perf",
}


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Tag gated test files before pytest applies -m deselection."""
    for item in items:
        marker = _GATE_MARKERS.get(item.path.stem)
        if marker is not None:
            item.add_marker(getattr(pytest.mark, marker))
