#!/usr/bin/env sh
set -eu

chart_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
common_args="--set controlPlaneURL=https://control-plane.example --set enrollment.existingSecret.name=data-plane-enrollment --set enrollment.existingSecret.key=token"

# shellcheck disable=SC2086
helm lint "$chart_dir" $common_args
# shellcheck disable=SC2086
helm template data-plane "$chart_dir" $common_args >/dev/null
# shellcheck disable=SC2086
helm template data-plane "$chart_dir" $common_args \
  --set image.digest=sha256:0123456789abcdef \
  --set networkPolicy.additionalEgress[0].cidr=198.51.100.0/24 \
  --set networkPolicy.additionalEgress[0].ports[0]=8443 >/dev/null

for bad_args in \
  "--set replicaCount=2" \
  "--set replicaCount=1.5" \
  "--set controlPlaneURL=http://control-plane.example" \
  "--set enrollment.existingSecret.name=" \
  "--set enrollment.existingSecret.key=" \
  "--set networkPolicy.additionalEgress[0].cidr=198.51.100.0/24"; do
  # shellcheck disable=SC2086
  if helm template data-plane "$chart_dir" $common_args $bad_args >/dev/null 2>&1; then
    echo "expected Helm rendering to fail for: $bad_args" >&2
    exit 1
  fi
done

echo "Helm render checks passed."
