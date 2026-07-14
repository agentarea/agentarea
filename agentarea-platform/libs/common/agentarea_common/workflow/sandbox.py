"""Shared Temporal workflow-sandbox configuration.

Every AgentArea worker (production and tests) must build its sandboxed
workflow runner from here so the passthrough set stays in one place.
"""

from temporalio.worker.workflow_sandbox import (
    SandboxedWorkflowRunner,
    SandboxRestrictions,
)

# Modules imported once outside the sandbox and reused inside, instead of being
# re-executed per workflow task. `opentelemetry` is required: the structured log
# formatter (WorkspaceContextFormatter) imports `opentelemetry.trace` to attach
# trace ids, and `opentelemetry.context` reads os.environ at import time. Under
# the default sandbox that env read raises RestrictedWorkflowAccessError and
# fails the workflow task — which Temporal then retries forever, hanging the run.
# Passthrough is Temporal's documented fix for libraries that touch os.environ.
_PASSTHROUGH_MODULES = ("opentelemetry",)


def create_workflow_runner() -> SandboxedWorkflowRunner:
    """Return the sandboxed workflow runner used by all AgentArea workers."""
    return SandboxedWorkflowRunner(
        SandboxRestrictions.default.with_passthrough_modules(*_PASSTHROUGH_MODULES)
    )
