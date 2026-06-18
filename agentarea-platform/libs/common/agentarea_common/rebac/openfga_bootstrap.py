"""Bootstrap helpers for OpenFGA stores and authorization models."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx
import yaml

from agentarea_common.config.openfga import OpenFGASettings

from .openfga_client import OpenFGAError, OpenFGAUnavailableError

logger = logging.getLogger(__name__)


async def bootstrap_openfga(
    settings: OpenFGASettings,
    *,
    client: httpx.AsyncClient | None = None,
) -> None:
    """Populate OpenFGA store/model ids on ``settings`` when bootstrap is enabled."""
    if not settings.ACCESS_CONTROL_OPENFGA_AUTO_BOOTSTRAP:
        return

    api_url = settings.ACCESS_CONTROL_OPENFGA_API_URL.rstrip("/")
    timeout = settings.ACCESS_CONTROL_OPENFGA_TIMEOUT_SECONDS
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=timeout)
    try:
        store_id = settings.ACCESS_CONTROL_OPENFGA_STORE_ID.strip()
        if not store_id:
            store_id = await _get_or_create_store(
                client=client,
                api_url=api_url,
                store_name=settings.ACCESS_CONTROL_OPENFGA_STORE_NAME,
            )
            settings.ACCESS_CONTROL_OPENFGA_STORE_ID = store_id

        if settings.ACCESS_CONTROL_OPENFGA_AUTO_APPLY_MODEL:
            model_path = settings.ACCESS_CONTROL_OPENFGA_MODEL_PATH
            if not model_path:
                raise OpenFGAError(
                    "ACCESS_CONTROL_OPENFGA_MODEL_PATH is required when model auto-apply is enabled"
                )
            model = _load_authorization_model(Path(model_path))
            model_id = await _find_authorization_model(client, api_url, store_id, model)
            if model_id is None:
                model_id = await _write_authorization_model(client, api_url, store_id, model)
            settings.ACCESS_CONTROL_OPENFGA_AUTHORIZATION_MODEL_ID = model_id
    finally:
        if owns_client:
            await client.aclose()


async def _get_or_create_store(*, client: httpx.AsyncClient, api_url: str, store_name: str) -> str:
    existing_store_id = await _find_store_id(client, api_url, store_name)
    if existing_store_id:
        return existing_store_id

    try:
        resp = await client.post(f"{api_url}/stores", json={"name": store_name})
    except httpx.HTTPError as exc:
        raise OpenFGAUnavailableError(f"OpenFGA store create unreachable: {exc}") from exc
    if resp.status_code not in {200, 201}:
        raise OpenFGAError(f"store create failed ({resp.status_code}): {resp.text}")

    # A second app/worker process can race the same create. Re-list and choose
    # the stable earliest store for this name so processes converge on one id.
    return await _find_store_id(client, api_url, store_name) or _store_id(resp.json())


async def _find_store_id(client: httpx.AsyncClient, api_url: str, store_name: str) -> str | None:
    stores: list[dict[str, Any]] = []
    continuation_token: str | None = None
    while True:
        params: dict[str, str] = {"page_size": "100"}
        if continuation_token:
            params["continuation_token"] = continuation_token
        try:
            resp = await client.get(f"{api_url}/stores", params=params)
        except httpx.HTTPError as exc:
            raise OpenFGAUnavailableError(f"OpenFGA store list unreachable: {exc}") from exc
        if resp.status_code != 200:
            raise OpenFGAError(f"store list failed ({resp.status_code}): {resp.text}")

        data = resp.json()
        stores.extend(
            store for store in data.get("stores") or [] if store.get("name") == store_name
        )
        continuation_token = data.get("continuation_token") or None
        if not continuation_token:
            break

    if not stores:
        return None

    stores.sort(key=lambda store: (store.get("created_at") or "", store.get("id") or ""))
    return _store_id(stores[0])


def _load_authorization_model(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise OpenFGAError(f"authorization model file is not readable: {path}") from exc
    if not isinstance(data, dict):
        raise OpenFGAError(f"authorization model file must contain an object: {path}")
    return data


async def _find_authorization_model(
    client: httpx.AsyncClient,
    api_url: str,
    store_id: str,
    model: dict[str, Any],
) -> str | None:
    expected = _normalize_authorization_model(model)
    continuation_token: str | None = None
    while True:
        params: dict[str, str] = {"page_size": "100"}
        if continuation_token:
            params["continuation_token"] = continuation_token
        try:
            resp = await client.get(
                f"{api_url}/stores/{store_id}/authorization-models",
                params=params,
            )
        except httpx.HTTPError as exc:
            raise OpenFGAUnavailableError(
                f"OpenFGA authorization model list unreachable: {exc}"
            ) from exc
        if resp.status_code != 200:
            raise OpenFGAError(f"authorization model list failed ({resp.status_code}): {resp.text}")

        data = resp.json()
        for candidate in data.get("authorization_models") or []:
            if _normalize_authorization_model(candidate) == expected:
                model_id = candidate.get("id") or candidate.get("authorization_model_id")
                return str(model_id) if model_id else None
        continuation_token = data.get("continuation_token") or None
        if not continuation_token:
            return None


async def _write_authorization_model(
    client: httpx.AsyncClient,
    api_url: str,
    store_id: str,
    model: dict[str, Any],
) -> str:
    try:
        resp = await client.post(f"{api_url}/stores/{store_id}/authorization-models", json=model)
    except httpx.HTTPError as exc:
        raise OpenFGAUnavailableError(
            f"OpenFGA authorization model write unreachable: {exc}"
        ) from exc
    if resp.status_code not in {200, 201}:
        raise OpenFGAError(f"authorization model write failed ({resp.status_code}): {resp.text}")

    data = resp.json()
    model_id = data.get("authorization_model_id") or data.get("id")
    if not model_id:
        raise OpenFGAError("authorization model write did not return a model id")
    return str(model_id)


def _store_id(data: dict[str, Any]) -> str:
    store_id = data.get("id")
    if not store_id:
        raise OpenFGAError("OpenFGA store response did not include an id")
    return str(store_id)


def _normalize_authorization_model(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, raw in value.items():
            item = _normalize_authorization_model(raw)
            if key in {"id", "authorization_model_id"}:
                continue
            if key in {"module", "source_info", "condition", "object"} and item in {"", None}:
                continue
            normalized[key] = item
        return {key: normalized[key] for key in sorted(normalized)}
    if isinstance(value, list):
        return [_normalize_authorization_model(item) for item in value]
    return value
