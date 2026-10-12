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

#: The model this code checks against. It ships inside the package, so the
#: relations a check names always exist in the model the process applies.
AUTHORIZATION_MODEL = Path(__file__).parent / "openfga" / "authorization-model.json"


async def bootstrap_openfga(
    settings: OpenFGASettings,
    *,
    client: httpx.AsyncClient | None = None,
    model_path: Path = AUTHORIZATION_MODEL,
) -> None:
    """Populate OpenFGA store/model ids on ``settings`` when bootstrap is enabled."""
    if not settings.BOOTSTRAP:
        return

    api_url = settings.URL.rstrip("/")
    timeout = settings.TIMEOUT.total_seconds()
    headers = {"Authorization": f"Bearer {settings.API_TOKEN}"} if settings.API_TOKEN else {}
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=timeout)
    try:
        store_id = settings.STORE_ID.strip()
        if not store_id:
            store_id = await _get_or_create_store(
                client=client,
                api_url=api_url,
                store_name=settings.STORE_NAME,
                headers=headers,
            )
            settings.STORE_ID = store_id

        if settings.APPLY_MODEL:
            model = _load_authorization_model(model_path)
            if settings.MODEL_PATH:
                custom = _load_authorization_model(Path(settings.MODEL_PATH))
                require_extends(custom, model)
                model = custom
            model_id = await _find_authorization_model(client, api_url, store_id, model, headers)
            if model_id is None:
                model_id = await _write_authorization_model(
                    client, api_url, store_id, model, headers
                )
            settings.MODEL_ID = model_id
    finally:
        if owns_client:
            await client.aclose()


async def _get_or_create_store(
    *, client: httpx.AsyncClient, api_url: str, store_name: str, headers: dict[str, str]
) -> str:
    existing_store_id = await _find_store_id(client, api_url, store_name, headers)
    if existing_store_id:
        return existing_store_id

    try:
        resp = await client.post(f"{api_url}/stores", json={"name": store_name}, headers=headers)
    except httpx.HTTPError as exc:
        raise OpenFGAUnavailableError(f"OpenFGA store create unreachable: {exc}") from exc
    if resp.status_code not in {200, 201}:
        raise OpenFGAError(f"store create failed ({resp.status_code}): {resp.text}")

    # A second app/worker process can race the same create. Re-list and choose
    # the stable earliest store for this name so processes converge on one id.
    return await _find_store_id(client, api_url, store_name, headers) or _store_id(resp.json())


async def _find_store_id(
    client: httpx.AsyncClient, api_url: str, store_name: str, headers: dict[str, str]
) -> str | None:
    stores: list[dict[str, Any]] = []
    continuation_token: str | None = None
    while True:
        params: dict[str, str] = {"page_size": "100"}
        if continuation_token:
            params["continuation_token"] = continuation_token
        try:
            resp = await client.get(f"{api_url}/stores", params=params, headers=headers)
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


def require_extends(custom: dict[str, Any], base: dict[str, Any]) -> None:
    """Refuse a custom model that drops or redefines anything of the packaged one.

    The platform's checks name the packaged model's relations, so a model
    without them fails every such check at runtime. Additions are the
    deployment's own; OpenFGA modular models (``extend type``) produce exactly
    that shape.
    """
    problems: list[str] = []
    custom_types = {t.get("type"): t for t in custom.get("type_definitions") or []}
    for base_type in base.get("type_definitions") or []:
        name = base_type.get("type")
        mine = custom_types.get(name)
        if mine is None:
            problems.append(f"type {name} is missing")
            continue
        base_meta = (base_type.get("metadata") or {}).get("relations") or {}
        mine_meta = (mine.get("metadata") or {}).get("relations") or {}
        for relation, rewrite in (base_type.get("relations") or {}).items():
            if relation not in (mine.get("relations") or {}):
                problems.append(f"{name}#{relation} is missing")
            elif _definition(mine["relations"][relation], mine_meta.get(relation)) != _definition(
                rewrite, base_meta.get(relation)
            ):
                problems.append(f"{name}#{relation} is redefined")
    custom_conditions = custom.get("conditions") or {}
    for condition, body in (base.get("conditions") or {}).items():
        if _without_provenance(custom_conditions.get(condition)) != _without_provenance(body):
            problems.append(f"condition {condition} is missing or redefined")
    if problems:
        raise OpenFGAError(
            "AGENTAREA_AUTHZ_FGA_MODEL_PATH must extend the packaged authorization model: "
            + "; ".join(problems)
        )


def _definition(rewrite: Any, metadata: Any) -> Any:
    return _without_provenance({"rewrite": rewrite, "metadata": metadata})


def _without_provenance(value: Any) -> Any:
    """A model element as OpenFGA evaluates it, without where a module declared it."""
    if isinstance(value, dict):
        stripped = {
            key: _without_provenance(item)
            for key, item in sorted(value.items())
            if key not in {"module", "source_info"}
        }
        return {key: item for key, item in stripped.items() if item not in ({}, [], None, "")}
    if isinstance(value, list):
        return [_without_provenance(item) for item in value]
    return value


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
    headers: dict[str, str],
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
                headers=headers,
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
    headers: dict[str, str],
) -> str:
    try:
        resp = await client.post(
            f"{api_url}/stores/{store_id}/authorization-models", json=model, headers=headers
        )
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
            if key in {"module", "source_info", "condition", "object"} and item in ("", None):
                continue
            # The server echoes absent collections back as empty ones.
            if item in ({}, []):
                continue
            normalized[key] = item
        return {key: normalized[key] for key in sorted(normalized)}
    if isinstance(value, list):
        return [_normalize_authorization_model(item) for item in value]
    return value
