#!/usr/bin/env bash
# The platform egress policy is off by default. Enabled, it must select exactly
# the backend, worker and event-service pods -- never an MCP instance, a sandbox
# or any other chart workload, whose own policies would otherwise be widened or
# narrowed -- keep every in-cluster pod reachable, and block the configured
# ranges, link-local by default.
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
renders="$(mktemp -d)"
trap 'rm -rf "$renders"' EXIT

extra='[{"to":[{"ipBlock":{"cidr":"10.42.0.10/32"}}]}]'

helm template egress "$repository_root/charts/agentarea" >"$renders/default.yaml"
helm template egress "$repository_root/charts/agentarea" \
  --set platformNetworkPolicy.enabled=true >"$renders/enabled.yaml"
helm template egress "$repository_root/charts/agentarea" \
  --set platformNetworkPolicy.enabled=true \
  --set-json "platformNetworkPolicy.extraEgress=$extra" >"$renders/extra.yaml"

python3 - "$renders" "$extra" <<'PY'
import json
import pathlib
import sys

import yaml

renders = pathlib.Path(sys.argv[1])
extra = json.loads(sys.argv[2])
failures = []


def load(name):
    return [doc for doc in yaml.safe_load_all((renders / f"{name}.yaml").read_text()) if doc]


def platform_policies(docs):
    return [
        doc
        for doc in docs
        if doc.get("kind") == "NetworkPolicy" and doc["metadata"]["name"].endswith("-platform-egress")
    ]


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


if platform_policies(load("default")):
    failures.append("default render ships the platform egress policy; it must be opt-in")

enabled = load("enabled")
policies = platform_policies(enabled)
if len(policies) != 1:
    failures.append(f"enabled render has {len(policies)} platform egress policies, want 1")
else:
    policy = policies[0]
    selector = policy["spec"]["podSelector"]
    workloads = {
        doc["metadata"]["name"]: doc["spec"]["template"]["metadata"].get("labels") or {}
        for doc in enabled
        if doc.get("kind") in {"Deployment", "StatefulSet", "DaemonSet", "Job"}
    }
    chosen = sorted(
        labels.get("app.kubernetes.io/component", name)
        for name, labels in workloads.items()
        if selects(selector, labels)
    )
    if chosen != ["backend", "event-service", "worker"]:
        failures.append(f"policy selects {chosen}, want backend, event-service, worker")

    # Pods the MCP manager creates are not in the render.
    for who, labels in {
        "MCP instance": {
            "app.kubernetes.io/name": "mcp-server",
            "app.kubernetes.io/instance": "instance",
            "app.kubernetes.io/managed-by": "mcp-manager",
            "app.kubernetes.io/component": "mcp-server",
        },
        "workflow sandbox": {
            "app.kubernetes.io/managed-by": "mcp-manager",
            "app.kubernetes.io/component": "workflow-sandbox",
        },
    }.items():
        if selects(selector, labels):
            failures.append(f"policy selects a {who} pod")

    if policy["spec"]["policyTypes"] != ["Egress"]:
        failures.append(f"policyTypes = {policy['spec']['policyTypes']}, want only Egress")
    rules = policy["spec"]["egress"]
    if {"to": [{"namespaceSelector": {}}]} not in rules:
        failures.append("in-cluster pods are not reachable")
    blocks = [peer["ipBlock"] for rule in rules for peer in rule.get("to") or [] if "ipBlock" in peer]
    if blocks != [{"cidr": "0.0.0.0/0", "except": ["169.254.0.0/16"]}]:
        failures.append(f"ipBlocks = {blocks}, want 0.0.0.0/0 except link-local")

extended = platform_policies(load("extra"))
if not extended or extended[0]["spec"]["egress"][-len(extra):] != extra:
    failures.append("extraEgress is not appended as-is")

if failures:
    print("\n".join(failures), file=sys.stderr)
    sys.exit(1)
print("platform egress policy: opt-in, selects backend/worker/event-service only, blocks link-local")
PY
