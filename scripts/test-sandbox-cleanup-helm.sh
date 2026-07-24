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


activation_secret = next(
    document
    for document in documents
    if "kind: Secret" in document and "sandbox-activation-secret:" in document
)
cleanup_secret = find_document("Secret", "cleanup-auth-agentarea-sandbox-cleanup-auth")
activation = re.search(
    r"(?m)^\s*sandbox-activation-secret:\s*([^\s]+)\s*$", activation_secret
)
cleanup = re.search(r"(?m)^\s*token:\s*([^\s]+)\s*$", cleanup_secret)
assert activation is not None, "activation secret is missing"
assert cleanup is not None, "cleanup secret is missing"
assert activation.group(1) != cleanup.group(1), "cleanup secret must be dedicated"

for component in ("mcp-manager", "worker"):
    deployment = find_document("Deployment", f"cleanup-auth-agentarea-{component}")
    assert deployment.count("name: SANDBOX_CLEANUP_AUTH_SECRET") == 1
    assert "name: cleanup-auth-agentarea-sandbox-cleanup-auth" in deployment
    assert "key: token" in deployment

for document in documents:
    if "app.kubernetes.io/component: sandbox-runner" in document or "app.kubernetes.io/component: warm-pool" in document:
        assert "SANDBOX_CLEANUP_AUTH_SECRET" not in document
        assert "cleanup-auth-agentarea-sandbox-cleanup-auth" not in document
PY
