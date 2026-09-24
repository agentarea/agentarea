#!/usr/bin/env bash
# The data-plane chart confines untrusted MCP servers. It must refuse to render a
# configuration that would weaken that silently -- no id, no token, no sandboxing
# RuntimeClass, an API bound to every interface -- and a complete configuration
# must carry every guard.
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
chart="$repository_root/charts/agentarea-dataplane"
rendered="$(mktemp)"
trap 'rm -f "$rendered"' EXIT

assert_fails() {
  local expected="$1"
  shift
  local output
  if output="$(helm template dp "$chart" "$@" 2>&1)"; then
    echo "expected a failed render naming '$expected', got a successful one" >&2
    exit 1
  fi
  if ! grep -q "$expected" <<<"$output"; then
    echo "render failed without naming '$expected':" >&2
    echo "$output" >&2
    exit 1
  fi
}

assert_fails "dataPlane.id is empty"
assert_fails "dataPlane.auth: set existingSecret" --set dataPlane.id=dp
assert_fails "at least 32 characters" --set dataPlane.id=dp --set dataPlane.auth.token=short
assert_fails "bindAddress is empty" --set dataPlane.id=dp --set dataPlane.auth.existingSecret=s \
  --set exposure.hostNetwork.enabled=true
assert_fails "runtimeClassName is empty" --set dataPlane.id=dp --set dataPlane.auth.existingSecret=s \
  --set workloads.runtimeClassName=

helm template dp "$chart" --set dataPlane.id=dp --set dataPlane.auth.existingSecret=s >"$rendered"

assert_contains() {
  if ! grep -q -- "$1" "$rendered"; then
    echo "rendered chart is missing: $1" >&2
    exit 1
  fi
}

# Every guard is on by default.
assert_contains "kind: ValidatingAdmissionPolicy$"
assert_contains "object.spec.runtimeClassName == 'gvisor'"
assert_contains "name: ingress-from-dataplane-only"
assert_contains "name: egress-dns-and-public-only"
assert_contains "pod-security.kubernetes.io/enforce: baseline"
assert_contains "automountServiceAccountToken: false"
assert_contains "value: \"gvisor\""
# Private ranges are closed to MCP servers, metadata included.
assert_contains "169.254.0.0/16"
assert_contains "10.0.0.0/8"
# Off the host network the API listens on the pod, behind a Service.
assert_contains "kind: Service$"

# Agent sandboxes get the same confinement, and the server refuses to render
# without a key or a sandboxing runtime.
sandboxes=(--set dataPlane.id=dp --set dataPlane.auth.existingSecret=s --set sandboxes.enabled=true)
assert_fails "sandboxes.server.auth: set existingSecret" "${sandboxes[@]}"
assert_fails "sandboxes.server.auth.apiKey must be at least 32" "${sandboxes[@]}" --set sandboxes.server.auth.apiKey=short
assert_fails "sandboxes.runtimeClassName is empty" "${sandboxes[@]}" --set sandboxes.server.auth.existingSecret=k \
  --set sandboxes.runtimeClassName=
assert_fails "sandboxes.server.port equals dataPlane.port" "${sandboxes[@]}" --set sandboxes.server.auth.existingSecret=k \
  --set exposure.hostNetwork.enabled=true --set exposure.hostNetwork.bindAddress=10.0.0.1 --set sandboxes.server.port=8090
assert_fails "opensandbox-controller.namespaceOverride" "${sandboxes[@]}" --set sandboxes.server.auth.existingSecret=k \
  --set opensandbox-controller.enabled=true --namespace elsewhere

helm template dp "$chart" "${sandboxes[@]}" --set sandboxes.server.auth.existingSecret=k \
  --set opensandbox-controller.enabled=true --namespace agentarea-system >"$rendered"
assert_contains "name: agentarea-sandboxes$"
assert_contains "name: dp-agentarea-dataplane-sandboxes-require-runtimeclass"
assert_contains "pods in agentarea-sandboxes must run with runtimeClassName gvisor"
assert_contains "name: ingress-from-sandbox-server-only"
assert_contains "port: 44772"
assert_contains 'k8s_runtime_class = "gvisor"'
assert_contains "automountServiceAccountToken: false"
assert_contains "kind: CustomResourceDefinition"
assert_contains "name: opensandbox-controller-manager"
# The server must not share the data plane's selector: it would sit behind the
# data plane's Service and inside the MCP servers' ingress policy.
assert_contains "app.kubernetes.io/name: agentarea-sandbox-server"
if [ "$(grep -c '^kind: NetworkPolicy' "$rendered")" != 4 ]; then
  echo "expected ingress and egress policies for both workload namespaces" >&2
  exit 1
fi

echo "data-plane chart guards hold"
