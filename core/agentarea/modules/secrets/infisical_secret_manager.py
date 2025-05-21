from infisical_sdk.client import InfisicalSDKClient

from agentarea.common.infrastructure.secret_manager import BaseSecretManager


class InfisicalSecretManager(BaseSecretManager):
    def __init__(self, infisical_client: InfisicalSDKClient):
        self.infisical_client = infisical_client

    async def get_secret(self, secret_name: str) -> str | None:
        secret = self.infisical_client.secrets.get_secret_by_name(
            project_id="default",
            environment_slug="default",
            secret_path=secret_name,
            secret_name=secret_name,
        )
        return secret.secretValue

    async def set_secret(self, secret_name: str, secret_value: str):
        self.infisical_client.secrets.create_secret_by_name(
            project_id="default",
            environment_slug="default",
            secret_path=secret_name,
            secret_value=secret_value,
            secret_name=secret_name,
        )
