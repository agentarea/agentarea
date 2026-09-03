from abc import ABC, abstractmethod


class BaseSecretManager(ABC):
    @abstractmethod
    async def get_secret(self, secret_name: str) -> str | None:
        pass

    @abstractmethod
    async def set_secret(self, secret_name: str, secret_value: str) -> None:
        pass

    @abstractmethod
    async def delete_secret(self, secret_name: str) -> bool:
        """Remove a secret. Returns False when there was nothing to remove.

        Abstract on purpose: the default used to return False without deleting
        anything, so a backend that forgot to implement it reported every
        deletion as a no-op and quietly kept the credential.
        """

    async def has_secret(self, secret_name: str) -> bool:
        """Whether a value is stored under this name.

        Concrete on purpose: every backend can answer it by reading the value,
        so no implementation is forced to write this. But a presence check has
        no business needing the plaintext — a backend that can answer without
        producing it should override, or a credential that has become
        unreadable (a rotated key, an unreachable store) turns "does this exist"
        into an error.
        """
        return await self.get_secret(secret_name) is not None

    @abstractmethod
    def external_ref(self, secret_name: str) -> str | None:
        """Where this backend keeps the value, or None if the catalog row holds it.

        The catalog needs this to know whether writing a secret also produced the
        row describing it. The database backend keeps both in one row and answers
        None; every other backend stores the value elsewhere, and the row it
        leaves behind records this address instead of a ciphertext.
        """

    # Listing lives on SecretCatalogService, not here. This interface is the
    # value store; the catalog is what knows which secrets exist, who owns them
    # and who uses them — none of which a name-only list could answer.
