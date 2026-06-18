"""Async HTTP client for OpenFGA's tuple graph APIs.

This adapter intentionally accepts AgentArea's existing RelationTuple shape so
the rest of the code can migrate from Keto without learning OpenFGA wire JSON.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .models import CheckResult, RelationQuery, RelationTuple, SubjectSet

logger = logging.getLogger(__name__)


class OpenFGAError(Exception):
    """An OpenFGA request returned an error response."""


class OpenFGAUnavailableError(OpenFGAError):
    """OpenFGA could not be reached."""


class OpenFGAClient:
    """Thin async client over OpenFGA's HTTP API."""

    def __init__(
        self,
        api_url: str,
        store_id: str,
        authorization_model_id: str | None = None,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not store_id:
            raise ValueError("OpenFGA store_id is required when OpenFGA is enabled")
        self._api_url = api_url.rstrip("/")
        self._store_id = store_id
        self._authorization_model_id = authorization_model_id
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

    async def __aenter__(self) -> OpenFGAClient:
        """Enter the async context, returning this client."""
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Exit the async context, closing the owned client."""
        await self.aclose()

    async def write_tuple(self, tuple_: RelationTuple) -> None:
        """Create a relation tuple."""
        await self._write({"writes": {"tuple_keys": [_tuple_key(tuple_)]}})

    async def delete_tuple(self, tuple_: RelationTuple) -> None:
        """Delete a relation tuple."""
        await self._write({"deletes": {"tuple_keys": [_tuple_key(tuple_)]}}, tolerate_404=True)

    async def query_tuples(self, query: RelationQuery) -> tuple[list[RelationTuple], str | None]:
        """List relation tuples matching ``query``. Returns (tuples, next_token)."""
        client = await self._http()
        url = f"{self._api_url}/stores/{self._store_id}/read"
        body: dict[str, Any] = {"page_size": query.page_size}
        key = _query_key(query)
        if "object" in key:
            body["tuple_key"] = key
        if query.page_token:
            body["continuation_token"] = query.page_token
        try:
            resp = await client.post(url, json=body)
        except httpx.HTTPError as exc:
            raise OpenFGAUnavailableError(f"OpenFGA read unreachable: {exc}") from exc
        if resp.status_code != 200:
            raise OpenFGAError(f"query_tuples failed ({resp.status_code}): {resp.text}")
        data = resp.json()
        tuples = [
            t
            for t in (_from_openfga_tuple(raw) for raw in data.get("tuples") or [])
            if _matches(t, query)
        ]
        return tuples, data.get("continuation_token") or None

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
        contextual_tuples: list[RelationTuple] | None = None,
    ) -> CheckResult:
        """Check whether ``subject_id`` has ``relation`` on ``namespace:object``."""
        client = await self._http()
        url = f"{self._api_url}/stores/{self._store_id}/check"
        body: dict[str, Any] = {
            "tuple_key": {
                "user": subject_id,
                "relation": relation,
                "object": _object_ref(namespace, object),
            }
        }
        if contextual_tuples:
            body["contextual_tuples"] = {
                "tuple_keys": [_tuple_key(tuple_) for tuple_ in contextual_tuples]
            }
        if self._authorization_model_id:
            body["authorization_model_id"] = self._authorization_model_id
        try:
            resp = await client.post(url, json=body)
        except httpx.HTTPError as exc:
            raise OpenFGAUnavailableError(f"OpenFGA check unreachable: {exc}") from exc
        if resp.status_code != 200:
            raise OpenFGAError(f"check failed ({resp.status_code}): {resp.text}")
        return CheckResult(allowed=bool(resp.json().get("allowed", False)))

    async def _write(self, body: dict[str, Any], *, tolerate_404: bool = False) -> None:
        client = await self._http()
        url = f"{self._api_url}/stores/{self._store_id}/write"
        try:
            resp = await client.post(url, json=body)
        except httpx.HTTPError as exc:
            raise OpenFGAUnavailableError(f"OpenFGA write unreachable: {exc}") from exc
        ok_statuses = {200, 204}
        if tolerate_404:
            ok_statuses.add(404)
        if resp.status_code not in ok_statuses:
            raise OpenFGAError(f"write failed ({resp.status_code}): {resp.text}")


def _object_ref(namespace: str, object_id: str) -> str:
    return f"{namespace}:{object_id}"


def _subject_ref(tuple_: RelationTuple) -> str:
    if tuple_.subject_id is not None:
        return tuple_.subject_id
    if tuple_.subject_set is None:  # pragma: no cover - model validator prevents this.
        raise ValueError("tuple has no subject")
    return _subject_set_ref(tuple_.subject_set)


def _subject_set_ref(subject_set: SubjectSet) -> str:
    return f"{subject_set.namespace}:{subject_set.object}#{subject_set.relation}"


def _tuple_key(tuple_: RelationTuple) -> dict[str, str]:
    return {
        "user": _subject_ref(tuple_),
        "relation": tuple_.relation,
        "object": _object_ref(tuple_.namespace, tuple_.object),
    }


def _query_key(query: RelationQuery) -> dict[str, str]:
    key: dict[str, str] = {}
    if query.subject_id is not None:
        key["user"] = query.subject_id
    elif query.subject_set is not None:
        key["user"] = _subject_set_ref(query.subject_set)
    if query.relation is not None:
        key["relation"] = query.relation
    if query.namespace is not None and query.object is not None:
        key["object"] = _object_ref(query.namespace, query.object)
    return key


def _from_openfga_tuple(data: dict[str, Any]) -> RelationTuple:
    key = data.get("key") or data
    namespace, object_id = _split_object_ref(key["object"])
    subject = key["user"]
    subject_set = _parse_subject_set(subject)
    return RelationTuple(
        namespace=namespace,
        object=object_id,
        relation=key["relation"],
        subject_id=None if subject_set else subject,
        subject_set=subject_set,
    )


def _matches(tuple_: RelationTuple, query: RelationQuery) -> bool:
    if query.namespace is not None and tuple_.namespace != query.namespace:
        return False
    if query.object is not None and tuple_.object != query.object:
        return False
    if query.relation is not None and tuple_.relation != query.relation:
        return False
    if query.subject_id is not None and tuple_.subject_id != query.subject_id:
        return False
    if query.subject_set is not None and tuple_.subject_set != query.subject_set:
        return False
    return True


def _split_object_ref(value: str) -> tuple[str, str]:
    namespace, object_id = value.split(":", 1)
    return namespace, object_id


def _parse_subject_set(value: str) -> SubjectSet | None:
    if "#" not in value:
        return None
    object_ref, relation = value.split("#", 1)
    namespace, object_id = _split_object_ref(object_ref)
    return SubjectSet(namespace=namespace, object=object_id, relation=relation)
