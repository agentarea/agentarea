#!/usr/bin/env bash
# Build and push all Docker images to Docker Hub with release tags.
# Run from the repo root: ./scripts/docker-build-push.sh
set -euo pipefail

VERSION=$(cat VERSION | tr -d '[:space:]')
SHORT_SHA=$(git rev-parse --short HEAD)
MAJOR=$(echo "$VERSION" | cut -d. -f1)
MINOR=$(echo "$VERSION" | cut -d. -f2)
MAJOR_MINOR="${MAJOR}.${MINOR}"

echo "Version:   $VERSION"
echo "Short SHA: $SHORT_SHA"
echo ""

# name | context | dockerfile | managed_environment
COMPONENTS=(
  "api|agentarea-platform|agentarea-platform/apps/api/Dockerfile|"
  "worker|agentarea-platform|agentarea-platform/apps/worker/Dockerfile|"
  "frontend|agentarea-webapp|agentarea-webapp/Dockerfile|"
  "operator|agentarea-operator|agentarea-operator/Dockerfile|"
  "mcp-manager|agentarea-mcp-manager|agentarea-mcp-manager/Dockerfile|"
  "mcp-runner|agentarea-mcp-manager|agentarea-mcp-manager/Dockerfile.runner|mutable"
  "mcp-runner-locked|agentarea-mcp-manager|agentarea-mcp-manager/Dockerfile.runner|immutable"
)

build_and_push() {
  local name="$1"
  local context="$2"
  local dockerfile="$3"
  local managed_environment="$4"
  local image="agentarea/agentarea-${name}"

  local tags=(
    "${image}:${VERSION}-${SHORT_SHA}"
    "${image}:${VERSION}"
    "${image}:${MAJOR_MINOR}-${SHORT_SHA}"
    "${image}:${MAJOR_MINOR}"
    "${image}:${MAJOR}-${SHORT_SHA}"
    "${image}:${MAJOR}"
    "${image}:latest"
  )

  echo "━━━ Building ${image} ━━━"

  local tag_args=()
  for tag in "${tags[@]}"; do
    tag_args+=(-t "$tag")
  done

  local build_args=()
  if [[ "$name" == "frontend" ]]; then
    build_args+=(--build-arg "APP_VERSION=${VERSION}")
  fi
  if [[ -n "$managed_environment" ]]; then
    build_args+=(--build-arg "MANAGED_ENVIRONMENT=${managed_environment}")
  fi

  docker buildx build \
    --platform linux/amd64,linux/arm64 \
    --file "$dockerfile" \
    "${tag_args[@]}" \
    "${build_args[@]}" \
    --push \
    "$context"

  echo "Done: ${image}"
  echo ""
}

# Optional: filter by component name(s) passed as args
# Usage: ./scripts/docker-build-push.sh mcp-manager mcp-runner mcp-runner-locked
FILTER=("$@")

for entry in "${COMPONENTS[@]}"; do
  IFS='|' read -r name context dockerfile managed_environment <<< "$entry"

  if [ ${#FILTER[@]} -gt 0 ]; then
    match=false
    for f in "${FILTER[@]}"; do
      [[ "$name" == "$f" ]] && match=true
    done
    $match || continue
  fi

  build_and_push "$name" "$context" "$dockerfile" "$managed_environment"
done

echo "All done."
