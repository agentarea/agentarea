from abc import ABC, abstractmethod


class BaseSecretManager(ABC):
    @abstractmethod
    async def get_secret(self, secret_name: str) -> str | None:
        pass

    @abstractmethod
    async def set_secret(self, secret_name: str, secret_value: str) -> None:
        pass

    async def delete_secret(self, secret_name: str) -> bool:
        return False

    async def list_secrets(self) -> list[str]:
        return []
