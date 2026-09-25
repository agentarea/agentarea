"""Credentials and provenance for the files agents read and write in their sandbox."""

from ...interfaces import ActivityDependencies


def sandbox_file_auth_secret(dependencies: ActivityDependencies) -> str:
    secret = dependencies.settings.mcp.SANDBOX_FILE_AUTH_SECRET
    if secret is None or not secret.get_secret_value():
        raise ValueError("SANDBOX_FILE_AUTH_SECRET is required for sandbox file access")
    return secret.get_secret_value()


def sandbox_control_auth_secret(dependencies: ActivityDependencies) -> str:
    secret = dependencies.settings.mcp.SANDBOX_CONTROL_AUTH_SECRET
    if secret is None:
        raise ValueError("SANDBOX_CONTROL_AUTH_SECRET is required for sandbox execution")
    value = secret.get_secret_value()
    if len(value.encode()) < 32:
        raise ValueError("SANDBOX_CONTROL_AUTH_SECRET must contain at least 32 bytes")
    return value


def agent_artifact_actor(request, user_context):
    """Build the provenance actor for files an agent writes during a task."""
    from agentarea_common.artifacts import ACTOR_AGENT, ArtifactActor

    agent_id = getattr(request, "agent_id", None)
    task_id = getattr(request, "task_id", None)
    return ArtifactActor(
        user_id=str(user_context.user_id),
        actor_type=ACTOR_AGENT,
        agent_id=str(agent_id) if agent_id else None,
        task_id=str(task_id) if task_id else None,
    )
