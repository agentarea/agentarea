"""Executable registry of the product's main flows.

Each `MainFlow` MUST have at least one test marked `@pytest.mark.flow(MainFlow.X)`,
unless it is listed in `PENDING_COVERAGE` (a tracked gap awaiting a hermetic test).
The coverage guard (``tests/unit/test_flow_coverage.py``) enforces both rules, so
the registry cannot silently rot: undeclared gaps fail CI, and a flow that gains a
test must be removed from `PENDING_COVERAGE`.

Run the canonical main-flow suite before a release with ``make test-flows``
(equivalent to ``pytest -m flow``).

Flows are deliberately *subcutaneous* (Fowler): they assert flow-level behaviour
just under the UI (workflow / service / API), not through a browser. The same flow
can be driven hermetically (mocked LLM) on every merge and against real infra on a
schedule — one spec, swappable driver.
"""

from enum import StrEnum


class MainFlow(StrEnum):
    """Canonical product flows that must always work before a release."""

    # --- Agent core ---
    AGENT_LIFECYCLE = "agent_lifecycle"  # create -> run task -> LLM loop -> completed
    SIGNALS_HITL = "signals_hitl"  # human-in-the-loop: request input / user signal
    TASK_INPUT = "task_input"  # submit structured input to a running task
    AGENT_TOOL_USE = "agent_tool_use"  # agent calls tools / runs code in the sandbox

    # --- Multi-agent ---
    A2A_DELEGATION = "a2a_delegation"  # coordinator delegates to specialist agents
    A2UI_ACTION = "a2ui_action"  # agent-to-UI action surface

    # --- MCP ---
    MCP_INSTANCE_LIFECYCLE = "mcp_instance_lifecycle"  # create -> spin up -> discovery
    MCP_PROXY = "mcp_proxy"  # per-instance reverse proxy (+ SSRF guard)
    MCP_OAUTH = "mcp_oauth"  # MCP OAuth connect / authorization-server flow
    OPENAPI_CONNECTIONS = "openapi_connections"  # OpenAPI-described tool connections

    # --- Models / providers ---
    PROVIDER_MODEL_CONFIG = "provider_model_config"  # provider + model instance config

    # --- Triggers / automation / channels ---
    TRIGGERS = "triggers"  # trigger fires -> task
    WEBHOOKS = "webhooks"  # inbound webhook -> trigger
    CHANNELS = "channels"  # inbound message -> agent -> outbound

    # --- Skills / bundles / registry ---
    SKILLS = "skills"  # skill CRUD + collections + disclosure
    BUNDLES = "bundles"  # bundle analyze / install
    REGISTRY_CATALOG = "registry_catalog"  # registry-catalog (built-ins on demand)

    # --- Auth / workspace / governance ---
    EXTENSION_CONTRACT = "extension_contract"  # OSS/Enterprise plugin seam
    AUTH_WORKSPACE_SCOPING = "auth_workspace_scoping"  # workspace isolation + ReBAC
    GOVERNANCE_POLICIES = "governance_policies"  # policy engine PAP/PDP/PEP

    # --- Commerce / files ---
    WALLET_PAYMENTS = "wallet_payments"  # agent wallet / x402 payment
    FILES_ARTIFACTS = "files_artifacts"  # file upload / artifact handling


# Flows declared above but not yet covered by a hermetic test. These are TRACKED
# gaps, not silent ones: the guard reports them and forbids adding undeclared gaps.
# Remove an entry as soon as a `@pytest.mark.flow` test exists for it (the guard
# enforces this — a covered flow may not stay in PENDING_COVERAGE).
# Empty: every MainFlow currently has a hermetic `@pytest.mark.flow` test.
# Add a flow here ONLY as a tracked, temporary gap (with a reason) when you
# introduce a new flow before its test exists.
PENDING_COVERAGE: set[MainFlow] = set()


# Populated during collection by the root conftest's pytest_collection_modifyitems.
COVERED_FLOWS: set[str] = set()
