#!/usr/bin/env bash
# No container may declare the same env name twice. Helm renders such a template
# happily, kubectl accepts it, and only server-side apply refuses it — with an
# error on the diff, not the apply, so Argo CD reports "Unknown" sync state and
# silently stops reconciling that Application while the old pods keep serving.
# The generated config groups and agentarea.sandboxRuntime.envs both emit
# SANDBOX_* variables, so this is a live collision risk on every chart change.
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
chart="$repository_root/charts/agentarea"
default_render="$(mktemp)"
external_render="$(mktemp)"
trap 'rm -f "$default_render" "$external_render"' EXIT

helm template dup-env "$chart" >"$default_render"

# The external-provider path renders the sandbox env helper into mcp-manager and
# sandbox-runner, which is where the collision appeared.
helm template dup-env "$chart" \
  --set sandboxRuntime.provider=opensandbox \
  --set sandboxRuntime.opensandbox.url=https://sandbox.example.com \
  --set sandboxRuntime.opensandbox.isolation=gvisor \
  --set sandboxRuntime.opensandbox.runtimeIdentity=test-runtime \
  --set sandboxRuntime.allowInternet=true \
  --set sandboxRuntime.opensandbox.egressMode=host-public \
  --set sandboxRuntime.opensandbox.image=example/runner@sha256:0000000000000000000000000000000000000000000000000000000000000000 \
  --set sandboxRuntime.opensandbox.apiKeySecretRef.name=sandbox-key \
  --set sandboxRuntime.opensandbox.apiKeySecretRef.key=api-key \
  --set sandboxRuntime.manifest.allowed.image_version=0.0.0 \
  --set sandboxRuntime.manifest.allowed.managed_environment=mutable \
  --set sandboxRuntime.manifest.allowed.python.version=3.12.13 \
  --set sandboxRuntime.manifest.allowed.python.executable=/usr/bin/python3 \
  --set sandboxRuntime.manifest.allowed.node.version=v22.23.2 \
  --set sandboxRuntime.manifest.allowed.features.browser=none \
  --set sandboxRuntime.manifest.allowed.features.managed_environment_mutation=true \
  --set sandboxRuntime.manifest.allowed.features.arbitrary_workspace_code=true \
  --set sandboxRuntime.manifest.allowed.execution_supervisor.path=/usr/local/bin/agentarea-exec-supervisor \
  --set sandboxRuntime.manifest.allowed.execution_supervisor.sha256=0000000000000000000000000000000000000000000000000000000000000000 \
  --set sandboxRuntime.manifest.allowed.execution_supervisor.protocol_version=1 \
  --set sandboxRuntime.manifest.allowed.execution_supervisor.command_uid=10001 \
  --set sandboxRuntime.manifest.allowed.execution_supervisor.command_gid=10001 \
  >"$external_render"

python3 - "$default_render" "$external_render" <<'PY'
import pathlib
import sys

import yaml

WORKLOADS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"}
failures = []

for path in sys.argv[1:]:
    label = pathlib.Path(path).name
    for doc in yaml.safe_load_all(pathlib.Path(path).read_text()):
        if not doc or doc.get("kind") not in WORKLOADS:
            continue
        spec = doc["spec"]
        # CronJob nests one more template than the rest.
        while "template" in spec:
            spec = spec["template"].get("spec", {})
        containers = spec.get("containers", []) + spec.get("initContainers", [])
        for container in containers:
            names = [entry["name"] for entry in container.get("env", []) or []]
            duplicates = sorted({name for name in names if names.count(name) > 1})
            if duplicates:
                failures.append(
                    f"{doc['kind']}/{doc['metadata']['name']} [{container['name']}]"
                    f" declares {', '.join(duplicates)} more than once"
                )

if failures:
    print("duplicate env names would be rejected by server-side apply:", file=sys.stderr)
    for failure in failures:
        print(f"  {failure}", file=sys.stderr)
    raise SystemExit(1)
PY

echo "OK: no container declares a duplicate env name"
