
from agentarea.common.infrastructure.secret_manager import BaseSecretManager


class DBSecretManager(BaseSecretManager):
    def __init__(self):
        self.secrets: dict[str, str] = {}

    async def get_secret(self, secret_name: str) -> str | None:
        return self.secrets.get(secret_name)

    async def set_secret(self, secret_name: str, secret_value: str):
        self.secrets[secret_name] = secret_value
