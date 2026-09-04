"""Workspace-scoped authentication for the internal sandbox control API."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class SandboxControlSigner:
    secret: str
    workspace_id: str
    task_id: str

    def __post_init__(self) -> None:
        if len(self.secret.encode()) < 32:
            raise ValueError("sandbox control auth secret must contain at least 32 bytes")
        if not self.workspace_id or not self.task_id:
            raise ValueError("workspace_id and task_id are required for sandbox control auth")

    def headers(
        self,
        scope: str,
        *,
        execution_id: str = "",
        body: bytes = b"",
    ) -> dict[str, str]:
        if scope not in {"execution.create", "execution.read", "execution.cancel"}:
            raise ValueError(f"unsupported sandbox control scope: {scope}")
        if scope == "execution.create" and execution_id:
            raise ValueError("create authorization cannot bind an execution id")
        if scope != "execution.create" and not execution_id:
            raise ValueError("execution id is required for read/cancel authorization")
        claims = {
            "v": 1,
            "scope": scope,
            "workspace_id": self.workspace_id,
            "task_id": self.task_id,
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "expires_at": int(time.time()) + 300,
            "nonce": secrets.token_hex(16),
        }
        if execution_id:
            claims["execution_id"] = execution_id
        payload = json.dumps(claims, separators=(",", ":"), sort_keys=True).encode()
        encoded = _base64url(payload)
        signature = _base64url(
            hmac.new(self.secret.encode(), encoded.encode(), hashlib.sha256).digest()
        )
        return {
            "Authorization": f"Bearer {encoded}.{signature}",
            "X-Agentarea-Workspace-ID": self.workspace_id,
            "X-Agentarea-Task-ID": self.task_id,
        }


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()
