#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rendered_chart="$(mktemp)"
trap 'rm -f "$rendered_chart"' EXIT

helm template cleanup-auth "$repository_root/charts/agentarea" >"$rendered_chart"

python3 - "$rendered_chart" <<'PY'
import pathlib
import re
import sys

rendered = pathlib.Path(sys.argv[1]).read_text()
documents = re.split(r"\n---\s*\n", rendered)


def find_document(kind: str, name: str) -> str:
    for document in documents:
        if f"kind: {kind}" in document and re.search(
            rf"(?m)^\s*name:\s*{re.escape(name)}\s*$", document
        ):
            return document
    raise AssertionError(f"missing rendered {kind} {name}")


assert not any(
    "kind: Secret" in document
    and re.search(r"(?m)^\s*name:\s*agentarea-runtime-credentials\s*$", document)
    for document in documents
), "the chart must reference, not generate, runtime credentials"

contracts = {
    "mcp-manager": {
        "SANDBOX_CLEANUP_AUTH_SECRET": "sandbox-cleanup-token",
        "SANDBOX_INSPECTION_AUTH_SECRET": "sandbox-inspection-token",
        "SANDBOX_FILE_AUTH_SECRET": "sandbox-file-token",
        "MCP_GATEWAY_AUTH_SECRET": "mcp-gateway-token",
    },
    "worker": {
        "SANDBOX_FILE_AUTH_SECRET": "sandbox-file-token",
        "MCP_GATEWAY_AUTH_SECRET": "mcp-gateway-token",
    },
    "backend": {
        "SANDBOX_INSPECTION_AUTH_SECRET": "sandbox-inspection-token",
        "SANDBOX_FILE_AUTH_SECRET": "sandbox-file-token",
        "MCP_GATEWAY_AUTH_SECRET": "mcp-gateway-token",
    },
}

all_runtime_envs = {
    name for component_contract in contracts.values() for name in component_contract
}
for component, expected in contracts.items():
    deployment = find_document("Deployment", f"cleanup-auth-agentarea-{component}")
    for env_name in all_runtime_envs:
        count = deployment.count(f"name: {env_name}")
        assert count == (1 if env_name in expected else 0), (
            f"{component} has unexpected count {count} for {env_name}"
        )
    for env_name, secret_key in expected.items():
        env_block = re.search(
            rf"(?m)^\s*- name:\s*{re.escape(env_name)}\s*$\n"
            rf"^\s*valueFrom:\s*$\n"
            rf"^\s*secretKeyRef:\s*$\n"
            rf"^\s*name:\s*agentarea-runtime-credentials\s*$\n"
            rf"^\s*key:\s*{re.escape(secret_key)}\s*$",
            deployment,
        )
        assert env_block is not None, f"{component} does not reference {env_name}/{secret_key}"

for document in documents:
    if "app.kubernetes.io/component: sandbox-runner" in document or "app.kubernetes.io/component: warm-pool" in document:
        for env_name in all_runtime_envs:
            assert env_name not in document
        assert "agentarea-runtime-credentials" not in document

# Command admission and the activation data plane must render from one policy
# value. A control-plane maximum larger than the executor maximum would accept
# work that the data plane later shortens or rejects.
manager_config = find_document("ConfigMap", "cleanup-auth-agentarea-env-mcpmanager")
assert re.search(
    r'(?m)^\s*SANDBOX_MAX_EXECUTION_TIMEOUT_SECONDS:\s*"1800"\s*$',
    manager_config,
), "manager timeout policy was not rendered from sandboxRuntime.maxExecutionTimeoutSeconds"
warm_pool = find_document("DaemonSet", "cleanup-auth-agentarea-warm-pool")
assert re.search(
    r'(?m)^\s*- name:\s*MAX_EXECUTION_TIMEOUT_SECONDS\s*$\n'
    r'^\s*value:\s*"1800"\s*$',
    warm_pool,
), "activation timeout diverged from the manager policy"
PY
