from agentarea.common.infrastructure.secret_manager import BaseSecretManager


class DBSecretManager(BaseSecretManager):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_secret(self, secret_name: str) -> str:
        secret = await self.session.execute(
            select(Secret).where(Secret.name == secret_name)
        )
        return secret.scalar_one().value
