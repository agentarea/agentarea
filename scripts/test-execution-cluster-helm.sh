#!/usr/bin/env bash
# The chart must be able to point mcp-manager at a separate execution cluster,
# and must refuse to render a half-configured one. A half-configuration that
# rendered would deploy in-cluster mode silently: untrusted MCP servers and
# agent sandboxes on the control plane's nodes, while the operator believes
# they were moved off.
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
chart="$repository_root/charts/agentarea"
unconfigured="$(mktemp)"
configured="$(mktemp)"
trap 'rm -f "$unconfigured" "$configured"' EXIT

helm template exec-cluster "$chart" >"$unconfigured"
helm template exec-cluster "$chart" \
  --set mcpManager.executionCluster.kubeconfigSecret=exec-kubeconfig \
  --set mcpManager.executionCluster.kubeconfigKey=kubeconfig >"$configured"

# Half-configuration must stop the render, naming the value to fix.
assert_fails() {
  local missing="$1" expected="$2"
  shift 2
  local output
  if output="$(helm template exec-cluster "$chart" "$@" 2>&1)"; then
    echo "expected a failed render with $missing missing, got a successful one" >&2
    exit 1
  fi
  if ! grep -q "$expected" <<<"$output"; then
    echo "render failed without naming $expected:" >&2
    echo "$output" >&2
    exit 1
  fi
}

assert_fails "kubeconfigKey" "kubeconfigKey is empty" \
  --set mcpManager.executionCluster.kubeconfigSecret=exec-kubeconfig
assert_fails "kubeconfigSecret" "kubeconfigSecret is empty" \
  --set mcpManager.executionCluster.kubeconfigKey=kubeconfig

python3 - "$unconfigured" "$configured" <<'PY'
import pathlib
import re
import sys

unconfigured, configured = (pathlib.Path(p).read_text() for p in sys.argv[1:3])


def documents(rendered: str) -> list[str]:
    return re.split(r"\n---\s*\n", rendered)


def deployment(rendered: str, name: str) -> str:
    for document in documents(rendered):
        if "kind: Deployment" in document and re.search(
            rf"(?m)^\s*name:\s*{re.escape(name)}\s*$", document
        ):
            return document
    raise AssertionError(f"missing rendered Deployment {name}")


def config_value(rendered: str, key: str) -> str:
    for document in documents(rendered):
        if "kind: ConfigMap" not in document or "-env-mcpmanager" not in document:
            continue
        match = re.search(rf'(?m)^\s*{key}:\s*"(.*)"\s*$', document)
        assert match is not None, f"{key} missing from the mcp-manager ConfigMap"
        return match.group(1)
    raise AssertionError("missing rendered mcp-manager env ConfigMap")


# Unconfigured: in-cluster discovery. The variable is declared so the value is
# visible, but empty, and nothing is mounted.
assert config_value(unconfigured, "KUBERNETES_KUBECONFIG") == ""
assert "execution-kubeconfig" not in unconfigured

# Configured: every process that builds a Kubernetes backend from this env
# block gets both the path and the file it names.
path = config_value(configured, "KUBERNETES_KUBECONFIG")
assert path == "/etc/agentarea/exec/kubeconfig", path

for component in ("mcp-manager", "sandbox-runner"):
    rendered = deployment(configured, f"exec-cluster-agentarea-{component}")
    assert "name: KUBERNETES_KUBECONFIG" in rendered, component
    mount = re.search(
        r"(?s)- name: execution-kubeconfig\n\s*mountPath: (\S+)\n\s*readOnly: (\S+)",
        rendered,
    )
    assert mount is not None, f"{component} has no execution kubeconfig mount"
    assert mount.group(1) == "/etc/agentarea/exec", component
    assert mount.group(2) == "true", component
    volume = re.search(
        r'(?s)- name: execution-kubeconfig\n\s*secret:\n\s*secretName: "([^"]+)"'
        r'.*?items:\n\s*- key: "([^"]+)"\n\s*path: "([^"]+)"',
        rendered,
    )
    assert volume is not None, f"{component} has no execution kubeconfig volume"
    assert volume.groups() == ("exec-kubeconfig", "kubeconfig", "kubeconfig"), component
PY
