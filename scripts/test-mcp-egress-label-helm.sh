#!/usr/bin/env bash
# An MCP pod labelled agentarea.io/egress leaves the default egress policy. That
# must never widen what it reaches: in both charts it has to be selected by
# exactly one egress policy, that policy may open DNS and the configured egress
# proxy only, and ingress still applies to it as to every other MCP pod.
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
renders="$(mktemp -d)"
trap 'rm -rf "$renders"' EXIT

proxy_namespace='{"matchLabels":{"kubernetes.io/metadata.name":"egress"}}'
proxy_pods='{"matchLabels":{"app.kubernetes.io/name":"egress-proxy"}}'
dataplane=(--kube-version 1.31.0 --set dataPlane.id=dp --set dataPlane.auth.existingSecret=s)

helm template egress "$repository_root/charts/agentarea" >"$renders/main-default.yaml"
helm template egress "$repository_root/charts/agentarea" \
  --set mcpManager.instanceNetworkPolicy.egressProxy.port=3128 \
  --set-json "mcpManager.instanceNetworkPolicy.egressProxy.namespaceSelector=$proxy_namespace" \
  --set-json "mcpManager.instanceNetworkPolicy.egressProxy.podSelector=$proxy_pods" \
  >"$renders/main-proxy.yaml"
helm template dp "$repository_root/charts/agentarea-dataplane" "${dataplane[@]}" \
  --set sandboxes.enabled=true --set sandboxes.server.auth.existingSecret=k >"$renders/dataplane-default.yaml"
helm template dp "$repository_root/charts/agentarea-dataplane" "${dataplane[@]}" \
  --set workloads.networkPolicy.egressProxy.port=3128 \
  --set-json "workloads.networkPolicy.egressProxy.namespaceSelector=$proxy_namespace" \
  --set-json "workloads.networkPolicy.egressProxy.podSelector=$proxy_pods" \
  >"$renders/dataplane-proxy.yaml"

python3 - "$renders" <<'PY'
import pathlib
import sys

import yaml

renders = pathlib.Path(sys.argv[1])
mcp_pod = {
    "app.kubernetes.io/name": "mcp-server",
    "app.kubernetes.io/instance": "instance",
    "app.kubernetes.io/managed-by": "mcp-manager",
    "app.kubernetes.io/component": "mcp-server",
}
# The main chart's policies carry no namespace: they land in the release's.
cases = {
    "main-default": (None, False),
    "main-proxy": (None, True),
    "dataplane-default": ("agentarea-mcp", False),
    "dataplane-proxy": ("agentarea-mcp", True),
}
failures = []


def selects(selector, labels):
    for key, value in (selector.get("matchLabels") or {}).items():
        if labels.get(key) != value:
            return False
    for expression in selector.get("matchExpressions") or []:
        key, operator = expression["key"], expression["operator"]
        values = expression.get("values") or []
        if operator == "Exists" and key not in labels:
            return False
        if operator == "DoesNotExist" and key in labels:
            return False
        if operator == "In" and labels.get(key) not in values:
            return False
        if operator == "NotIn" and key in labels and labels[key] in values:
            return False
    return True


for name, (namespace, proxy) in cases.items():
    policies = [
        doc
        for doc in yaml.safe_load_all((renders / f"{name}.yaml").read_text())
        if doc and doc.get("kind") == "NetworkPolicy" and doc["metadata"].get("namespace") == namespace
    ]
    for labelled in (False, True):
        pod = dict(mcp_pod, **({"agentarea.io/egress": "exit"} if labelled else {}))
        who = f"{name}: {'labelled' if labelled else 'unlabelled'} MCP pod"
        chosen = [p for p in policies if selects(p["spec"]["podSelector"], pod)]
        egress = [p for p in chosen if "Egress" in p["spec"]["policyTypes"]]
        ingress = [p for p in chosen if "Ingress" in p["spec"]["policyTypes"]]
        if len(egress) != 1:
            failures.append(f"{who} is selected by {len(egress)} egress policies: {[p['metadata']['name'] for p in egress]}")
            continue
        if not ingress:
            failures.append(f"{who} is selected by no ingress policy")
        if not labelled:
            continue
        rules = egress[0]["spec"].get("egress") or []
        peers = [peer for rule in rules for peer in rule.get("to") or [{}]]
        if any("ipBlock" in peer or not peer for peer in peers):
            failures.append(f"{who} may reach an address range: {rules}")
        ports = sorted(port["port"] for rule in rules for port in rule.get("ports") or [])
        want = [53, 53, 3128] if proxy else [53, 53]
        if ports != want:
            failures.append(f"{who} egress ports = {ports}, want {want}")

if failures:
    print("\n".join(failures), file=sys.stderr)
    sys.exit(1)
print("labelled MCP pods get exactly one egress policy: DNS and the egress proxy only")
PY
