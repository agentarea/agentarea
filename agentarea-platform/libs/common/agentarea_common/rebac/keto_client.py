"""Async HTTP client for Ory Keto's read and write APIs.

Wraps the relation-tuple endpoints used by the access explorer:

- write API (default ``:4467``): ``PUT/DELETE /admin/relation-tuples``
- read API (default ``:4466``): ``GET /relation-tuples``,
  ``GET /relation-tuples/check``, ``GET /relation-tuples/expand``
"""

from __future__ import annotations

import logging

import httpx

from .models import CheckResult, ExpandNode, RelationQuery, RelationTuple

logger = logging.getLogger(__name__)


class KetoError(Exception):
    """A Keto request returned an error response."""


class KetoUnavailableError(KetoError):
    """Keto could not be reached (network/connection failure)."""


class KetoClient:
    """Thin async client over the Keto read/write APIs.

    Construct with the read and write base URLs (see ``KetoSettings``). The
    client owns its own ``httpx.AsyncClient`` unless one is injected (tests).
    """

    def __init__(
        self,
        read_url: str,
        write_url: str,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._read_url = read_url.rstrip("/")
        self._write_url = write_url.rstrip("/")
        self._timeout = timeout_seconds
        self._client = client
        self._owns_client = client is None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> KetoClient:
        """Enter the async context, returning self."""
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Exit the async context, closing the owned HTTP client."""
        await self.aclose()

    # -- write API ---------------------------------------------------------

    async def write_tuple(self, tuple_: RelationTuple) -> None:
        """Create (idempotent upsert) a relation tuple."""
        client = await self._http()
        url = f"{self._write_url}/admin/relation-tuples"
        try:
            resp = await client.put(url, json=tuple_.to_keto())
        except httpx.HTTPError as exc:
            raise KetoUnavailableError(f"Keto write unreachable: {exc}") from exc
        if resp.status_code not in (200, 201):
            raise KetoError(f"write_tuple failed ({resp.status_code}): {resp.text}")

    async def delete_tuple(self, tuple_: RelationTuple) -> None:
        """Delete a single relation tuple (no error if it does not exist)."""
        client = await self._http()
        url = f"{self._write_url}/admin/relation-tuples"
        params = _delete_params(tuple_)
        try:
            resp = await client.delete(url, params=params)
        except httpx.HTTPError as exc:
            raise KetoUnavailableError(f"Keto write unreachable: {exc}") from exc
        if resp.status_code not in (204, 200, 404):
            raise KetoError(f"delete_tuple failed ({resp.status_code}): {resp.text}")

    # -- read API ----------------------------------------------------------

    async def query_tuples(self, query: RelationQuery) -> tuple[list[RelationTuple], str | None]:
        """List relation tuples matching ``query``. Returns (tuples, next_token)."""
        client = await self._http()
        url = f"{self._read_url}/relation-tuples"
        try:
            resp = await client.get(url, params=query.to_params())
        except httpx.HTTPError as exc:
            raise KetoUnavailableError(f"Keto read unreachable: {exc}") from exc
        if resp.status_code != 200:
            raise KetoError(f"query_tuples failed ({resp.status_code}): {resp.text}")
        data = resp.json()
        tuples = [RelationTuple.from_keto(t) for t in data.get("relation_tuples") or []]
        return tuples, data.get("next_page_token") or None

    async def query_all_tuples(self, query: RelationQuery) -> list[RelationTuple]:
        """List every matching tuple, following pagination."""
        out: list[RelationTuple] = []
        token: str | None = None
        while True:
            page_query = query.model_copy(update={"page_token": token})
            tuples, token = await self.query_tuples(page_query)
            out.extend(tuples)
            if not token:
                return out

    async def check(
        self,
        namespace: str,
        object: str,
        relation: str,
        subject_id: str,
        max_depth: int = 10,
    ) -> CheckResult:
        """Check whether ``subject_id`` has ``relation`` on ``namespace:object``."""
        client = await self._http()
        url = f"{self._read_url}/relation-tuples/check"
        params = {
            "namespace": namespace,
            "object": object,
            "relation": relation,
            "subject_id": subject_id,
            "max-depth": str(max_depth),
        }
        try:
            resp = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise KetoUnavailableError(f"Keto check unreachable: {exc}") from exc
        # Keto returns 200 {allowed:true} or 403 {allowed:false}.
        if resp.status_code in (200, 403):
            return CheckResult(allowed=bool(resp.json().get("allowed", False)))
        raise KetoError(f"check failed ({resp.status_code}): {resp.text}")

    async def expand(
        self,
        namespace: str,
        object: str,
        relation: str,
        max_depth: int = 10,
    ) -> ExpandNode | None:
        """Expand the subject tree for ``namespace:object#relation``."""
        client = await self._http()
        url = f"{self._read_url}/relation-tuples/expand"
        params = {
            "namespace": namespace,
            "object": object,
            "relation": relation,
            "max-depth": str(max_depth),
        }
        try:
            resp = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise KetoUnavailableError(f"Keto expand unreachable: {exc}") from exc
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise KetoError(f"expand failed ({resp.status_code}): {resp.text}")
        return ExpandNode.from_keto(resp.json())


def _delete_params(tuple_: RelationTuple) -> dict[str, str]:
    params: dict[str, str] = {
        "namespace": tuple_.namespace,
        "object": tuple_.object,
        "relation": tuple_.relation,
    }
    if tuple_.subject_id is not None:
        params["subject_id"] = tuple_.subject_id
    elif tuple_.subject_set is not None:
        params["subject_set.namespace"] = tuple_.subject_set.namespace
        params["subject_set.object"] = tuple_.subject_set.object
        params["subject_set.relation"] = tuple_.subject_set.relation
    return params
