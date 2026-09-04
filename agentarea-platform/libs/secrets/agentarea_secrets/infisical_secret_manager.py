from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from infisical_sdk.client import InfisicalSDKClient


class InfisicalSecretManager(BaseSecretManager):
    """Infisical-backed secret storage, scoped per workspace.

    Every workspace gets its own secret path. Without one, two workspaces using
    the same secret name would read and overwrite each other's value — secret
    names are only unique within a workspace, and several are chosen by users.
    """

    def __init__(
        self,
        infisical_client: InfisicalSDKClient,
        workspace_id: str,
        project_id: str,
        environment_slug: str,
    ) -> None:
        self.infisical_client = infisical_client
        self.workspace_id = workspace_id
        self.project_id = project_id
        self.environment_slug = environment_slug

    @property
    def _secret_path(self) -> str:
        return f"/workspaces/{self.workspace_id}"

    def external_ref(self, secret_name: str) -> str:
        """Infisical holds the value; the catalog row records where."""
        return f"infisical://{self.project_id}/{self.environment_slug}{self._secret_path}/{secret_name}"

    async def get_secret(self, secret_name: str) -> str | None:
        # Only a genuine absence is None. Every other failure — an unreachable
        # host, a rejected identity, an expired token — propagates, because a
        # caller told "no such secret" goes looking in the wrong place.
        try:
            secret = self.infisical_client.secrets.get_secret_by_name(
                project_id=self.project_id,
                environment_slug=self.environment_slug,
                secret_path=self._secret_path,
                secret_name=secret_name,
            )
        except Exception as exc:
            if _is_not_found(exc):
                return None
            raise
        return secret.secretValue

    async def set_secret(self, secret_name: str, secret_value: str) -> None:
        if await self.get_secret(secret_name) is None:
            self.infisical_client.secrets.create_secret_by_name(
                project_id=self.project_id,
                environment_slug=self.environment_slug,
                secret_path=self._secret_path,
                secret_name=secret_name,
                secret_value=secret_value,
            )
        else:
            self.infisical_client.secrets.update_secret_by_name(
                current_secret_name=secret_name,
                project_id=self.project_id,
                environment_slug=self.environment_slug,
                secret_path=self._secret_path,
                secret_value=secret_value,
            )

    async def delete_secret(self, secret_name: str) -> bool:
        if await self.get_secret(secret_name) is None:
            return False
        self.infisical_client.secrets.delete_secret_by_name(
            secret_name=secret_name,
            project_id=self.project_id,
            environment_slug=self.environment_slug,
            secret_path=self._secret_path,
        )
        return True


def _is_not_found(exc: Exception) -> bool:
    """Distinguish "no such secret" from a backend that could not answer."""
    status_code = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    if status_code == 404:
        return True
    return "not found" in str(exc).lower()
