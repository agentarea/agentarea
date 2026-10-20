#!/usr/bin/env bash
# Artifact Hub scans the images a chart lists in its `artifacthub.io/images`
# annotation, and only renders the chart itself when the annotation is absent.
# The data-plane chart does not render without required values, so without the
# annotation it is never scanned; with a stale one, Artifact Hub reports on
# images the chart no longer runs. Each chart's annotation must name exactly the
# images its default and optional components deploy.
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

helm template aa "$repository_root/charts/agentarea" >"$workdir/agentarea.yaml"

# Every optional component on: agent sandboxes and the vendored controller, which
# keeps its namespace fixed and refuses any other release namespace.
helm template dp "$repository_root/charts/agentarea-dataplane" \
  --kube-version 1.31.0 \
  --namespace agentarea-system \
  --set dataPlane.id=dp \
  --set dataPlane.auth.existingSecret=s \
  --set sandboxes.enabled=true \
  --set sandboxes.server.auth.existingSecret=k \
  --set opensandbox-controller.enabled=true \
  >"$workdir/agentarea-dataplane.yaml"

python3 - "$repository_root/charts" "$workdir" <<'PY'
import pathlib
import sys

import yaml

charts_dir = pathlib.Path(sys.argv[1])
workdir = pathlib.Path(sys.argv[2])

# Images a chart deploys without a container of its own naming them: the
# OpenSandbox server copies execd into every sandbox it creates.
VALUE_IMAGES = {
    "agentarea": [],
    "agentarea-dataplane": ["sandboxes.server.execdImage"],
}


def rendered_images(path):
    images = set()
    for doc in yaml.safe_load_all(path.read_text()):
        stack = [doc]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in ("containers", "initContainers") and isinstance(value, list):
                        images.update(c["image"] for c in value if isinstance(c, dict) and "image" in c)
                    stack.append(value)
            elif isinstance(node, list):
                stack.extend(node)
    return images


def value_at(values, dotted):
    for part in dotted.split("."):
        values = values[part]
    return values


failures = []
for chart, value_paths in VALUE_IMAGES.items():
    chart_dir = charts_dir / chart
    expected = rendered_images(workdir / f"{chart}.yaml")
    values = yaml.safe_load((chart_dir / "values.yaml").read_text())
    expected.update(value_at(values, path) for path in value_paths)

    metadata = yaml.safe_load((chart_dir / "Chart.yaml").read_text())
    annotation = (metadata.get("annotations") or {}).get("artifacthub.io/images")
    listed = {entry["image"] for entry in yaml.safe_load(annotation or "") or []}

    if listed != expected:
        lines = [f"{chart}: artifacthub.io/images does not match the images the chart deploys"]
        lines += [f"  missing: {image}" for image in sorted(expected - listed)]
        lines += [f"  stale:   {image}" for image in sorted(listed - expected)]
        lines.append("  expected annotation:")
        lines.append("    artifacthub.io/images: |")
        for image in sorted(expected):
            parts = image.split("@")[0].rsplit(":", 1)[0].split("/")
            name = "/".join(parts[1:] if "." in parts[0] else parts)
            lines.append(f"      - name: {name}")
            lines.append(f"        image: {image}")
        failures.append("\n".join(lines))

if failures:
    print("\n".join(failures), file=sys.stderr)
    raise SystemExit(1)
PY

echo "OK: artifacthub.io/images lists exactly the images each chart deploys"
