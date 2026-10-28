#!/usr/bin/env bash
# The chart must run against an S3-compatible store other than the bundled RustFS.
# With rustfs.enabled=false every workload still gets AGENTAREA_S3_* from the
# storage ConfigMap and the operator's Secret, and the chart refuses to render
# when the external store is half-configured or configured alongside RustFS.
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
chart="$repository_root/charts/agentarea"
external_render="$(mktemp)"
bundled_render="$(mktemp)"
trap 'rm -f "$external_render" "$bundled_render"' EXIT

helm template ext "$chart" \
  --set rustfs.enabled=false \
  --set global.storage.endpoint=https://storage.example.com \
  --set global.storage.region=eu-west-1 \
  --set global.storage.existingSecret=object-store-keys \
  --set global.storage.accessKeyKey=id \
  --set global.storage.secretKeyKey=secret \
  >"$external_render"

helm template ext "$chart" >"$bundled_render"

python3 - "$external_render" "$bundled_render" <<'PY'
import pathlib
import sys

import yaml

WORKLOADS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"}
STORAGE_WORKLOADS = {
    "ext-agentarea-backend",
    "ext-agentarea-worker",
    "ext-agentarea-mcp-manager",
    "ext-agentarea-sandbox-runner",
}


def docs(path):
    return [d for d in yaml.safe_load_all(pathlib.Path(path).read_text()) if d]


def containers(doc):
    spec = doc["spec"]
    while "template" in spec:
        spec = spec["template"].get("spec", {})
    return spec.get("containers", [])


def check(path, endpoint, secret, access_key, secret_key, expect_rustfs):
    failures = []
    rendered = docs(path)
    configmaps = {d["metadata"]["name"]: d for d in rendered if d["kind"] == "ConfigMap"}
    storage = configmaps.get("ext-agentarea-env-storage")
    if storage is None:
        failures.append("ConfigMap ext-agentarea-env-storage is not rendered")
    elif storage["data"].get("AGENTAREA_S3_ENDPOINT") != endpoint:
        failures.append(
            f"AGENTAREA_S3_ENDPOINT is {storage['data'].get('AGENTAREA_S3_ENDPOINT')!r}, want {endpoint!r}"
        )

    seen = set()
    for doc in rendered:
        if doc["kind"] not in WORKLOADS or doc["metadata"]["name"] not in STORAGE_WORKLOADS:
            continue
        seen.add(doc["metadata"]["name"])
        env = {e["name"]: e for c in containers(doc) for e in c.get("env", []) or []}
        for name, key in (("AGENTAREA_S3_ACCESS_KEY", access_key), ("AGENTAREA_S3_SECRET_KEY", secret_key)):
            ref = env.get(name, {}).get("valueFrom", {}).get("secretKeyRef")
            if ref != {"name": secret, "key": key}:
                failures.append(f"{doc['metadata']['name']}: {name} reads {ref}, want {secret}/{key}")
        if "AGENTAREA_S3_ENDPOINT" not in env:
            failures.append(f"{doc['metadata']['name']}: AGENTAREA_S3_ENDPOINT is missing")
    for missing in sorted(STORAGE_WORKLOADS - seen):
        failures.append(f"{missing} is not rendered")

    has_rustfs = any(d["kind"] == "Deployment" and d["metadata"]["name"] == "ext-rustfs" for d in rendered)
    if has_rustfs != expect_rustfs:
        failures.append(f"RustFS Deployment rendered={has_rustfs}, want {expect_rustfs}")
    return [f"{pathlib.Path(path).name}: {f}" for f in failures]


failures = check(sys.argv[1], "https://storage.example.com", "object-store-keys", "id", "secret", False)
failures += check(sys.argv[2], "http://ext-rustfs:9000", "agentarea-rustfs-secret", "root-user", "root-password", True)
if failures:
    print("object storage wiring is wrong:", file=sys.stderr)
    for failure in failures:
        print(f"  {failure}", file=sys.stderr)
    raise SystemExit(1)
PY

expect_refusal() {
  local want="$1"
  shift
  local output
  if output="$(helm template ext "$chart" "$@" 2>&1 >/dev/null)"; then
    echo "chart rendered with $* but should have refused" >&2
    exit 1
  fi
  if [[ "$output" != *"$want"* ]]; then
    echo "chart refused $* without naming $want:" >&2
    echo "$output" >&2
    exit 1
  fi
}

expect_refusal "global.storage.endpoint" --set rustfs.enabled=false --set global.storage.existingSecret=object-store-keys
expect_refusal "global.storage.existingSecret" --set rustfs.enabled=false --set global.storage.endpoint=https://storage.example.com
expect_refusal "rustfs.enabled" --set global.storage.endpoint=https://storage.example.com
expect_refusal "rustfs.enabled" --set global.storage.existingSecret=object-store-keys

echo "OK: object storage is wired for both the bundled RustFS and an external store"
