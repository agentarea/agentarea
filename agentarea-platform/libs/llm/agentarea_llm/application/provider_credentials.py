"""Read a provider configuration's credential from the workspace that owns it."""

from agentarea_common.auth.context import UserContext
from agentarea_common.constants import MANAGED_BY_PLATFORM
from agentarea_secrets.secret_manager_factory import SecretManagerFactory


async def resolve_provider_api_key(
    *,
    reference: str | None,
    managed_by: str | None,
    user_context: UserContext,
    secret_manager_factory: SecretManagerFactory,
) -> str | None:
    """Read the credential this call runs on, from the workspace that owns it.

    ``reference`` is a secret name in both cases. What differs is whose secrets are
    searched, which is the whole reason this is one function and not a branch
    repeated at each call site:

      * tenant configuration (managed_by unset) — the caller's own workspace;
      * platform configuration — the platform workspace, which only the operator
        writes and which no tenant-scoped read can reach. The scoping that keeps
        tenants out of each other's secrets is what keeps them out of this one.

    Getting this branch wrong in either direction is silent: the name resolves to
    None in the wrong workspace and the provider answers 401, which reads as "the
    user's key is broken" — the one thing neither case is.
    """
    if not reference:
        return None

    from agentarea_common.config import get_database

    if managed_by == MANAGED_BY_PLATFORM:
        from agentarea_common.constants import PLATFORM_PRINCIPAL_ID, PLATFORM_WORKSPACE_ID

        secret_context = UserContext(
            user_id=PLATFORM_PRINCIPAL_ID,
            workspace_id=PLATFORM_WORKSPACE_ID,
        )
    else:
        secret_context = user_context

    secret_session = get_database().async_session_factory()
    try:
        secret_manager = secret_manager_factory.create(
            session=secret_session, user_context=secret_context
        )
        return await secret_manager.get_secret(reference)
    finally:
        await secret_session.close()
