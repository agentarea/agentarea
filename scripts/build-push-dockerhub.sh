#!/bin/bash
#
# Build and push all AgentArea containers to Docker Hub
#
# Usage:
#   export DOCKERHUB_USERNAME=your-username
#   export DOCKERHUB_PASSWORD=your-password
#   ./scripts/build-push-dockerhub.sh [push-latest]
#
# Arguments:
#   push-latest: Set to "true" to also push as "latest" tag (default: false)
#
# This script builds all containers for linux/amd64 and pushes them to Docker Hub
# with tags based on the VERSION file and optional commit SHA.

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Get the script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Parse arguments
PUSH_LATEST="${1:-false}"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Building and pushing containers to Docker Hub${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Platform: linux/amd64${NC}"
echo ""

# Check if docker is available
if ! command -v docker &> /dev/null; then
  echo -e "${RED}ERROR: docker command not found${NC}"
  exit 1
fi

# Check if docker buildx is available
if ! docker buildx version &> /dev/null; then
  echo -e "${RED}ERROR: docker buildx not available${NC}"
  exit 1
fi

# Read VERSION file
VERSION_FILE="${PROJECT_ROOT}/VERSION"
if [ ! -f "$VERSION_FILE" ]; then
  echo -e "${RED}ERROR: VERSION file not found at $VERSION_FILE${NC}"
  exit 1
fi

VERSION=$(cat "$VERSION_FILE" | tr -d '[:space:]')
if [ -z "$VERSION" ]; then
  echo -e "${RED}ERROR: VERSION file is empty${NC}"
  exit 1
fi

echo -e "${BLUE}Version: $VERSION${NC}"
echo ""

# Get commit SHA if available
if git rev-parse --git-dir > /dev/null 2>&1; then
  SHORT_SHA=$(git rev-parse --short HEAD)
  echo -e "${BLUE}Commit SHA: $SHORT_SHA${NC}"
else
  SHORT_SHA=""
  echo -e "${YELLOW}Warning: Not in a git repository, skipping SHA tag${NC}"
fi

echo ""

# Create buildx builder if it doesn't exist
BUILDER_NAME="agentarea-linux-builder"
if ! docker buildx inspect "$BUILDER_NAME" &> /dev/null; then
  echo -e "${BLUE}Creating buildx builder: $BUILDER_NAME${NC}"
  docker buildx create --name "$BUILDER_NAME" --use --platform linux/amd64
else
  echo -e "${BLUE}Using existing buildx builder: $BUILDER_NAME${NC}"
  docker buildx use "$BUILDER_NAME"
fi

# Check Docker Hub credentials
if [ -z "$DOCKERHUB_USERNAME" ] || [ -z "$DOCKERHUB_PASSWORD" ]; then
  echo -e "${RED}ERROR: DOCKERHUB_USERNAME and DOCKERHUB_PASSWORD environment variables are required${NC}"
  echo -e "${YELLOW}Please set them before running this script${NC}"
  echo -e "${YELLOW}Example: export DOCKERHUB_USERNAME=your-username${NC}"
  echo -e "${YELLOW}Example: export DOCKERHUB_PASSWORD=your-password${NC}"
  exit 1
fi

# Log in to Docker Hub
echo -e "${BLUE}Logging into Docker Hub...${NC}"
if ! echo "$DOCKERHUB_PASSWORD" | docker login --username "$DOCKERHUB_USERNAME" --password-stdin; then
  echo -e "${RED}ERROR: Failed to login to Docker Hub${NC}"
  exit 1
fi

echo ""

# Components to build and push
# Format: component|context|dockerfile
COMPONENTS=(
  "api|agentarea-platform|apps/api/Dockerfile"
  "worker|agentarea-platform|apps/worker/Dockerfile"
  "frontend|agentarea-webapp|Dockerfile"
  "bootstrap|agentarea-bootstrap|Dockerfile"
  "mcp-manager|agentarea-mcp-manager|Dockerfile"
)

FAILED=0
SUCCESS=0
FAILED_COMPONENTS=()

for component_info in "${COMPONENTS[@]}"; do
  IFS='|' read -r component context dockerfile <<< "$component_info"
  
  IMAGE_NAME="agentarea/agentarea-${component}"
  
  # Build tags
  TAGS=()
  TAGS+=("${IMAGE_NAME}:${VERSION}")
  
  if [ -n "$SHORT_SHA" ]; then
    TAGS+=("${IMAGE_NAME}:${VERSION}-${SHORT_SHA}")
  fi
  
  if [ "$PUSH_LATEST" == "true" ]; then
    TAGS+=("${IMAGE_NAME}:latest")
  fi
  
  # Convert tags array to docker buildx format
  TAG_ARGS=""
  for tag in "${TAGS[@]}"; do
    TAG_ARGS="${TAG_ARGS} --tag ${tag}"
  done
  
  echo -e "${BLUE}========================================${NC}"
  echo -e "${BLUE}Processing: $component${NC}"
  echo -e "${BLUE}Context: $context${NC}"
  echo -e "${BLUE}Dockerfile: $dockerfile${NC}"
  echo -e "${BLUE}Image: $IMAGE_NAME${NC}"
  echo -e "${BLUE}Tags: ${TAGS[*]}${NC}"
  echo ""
  
  # Build the image
  echo -e "${BLUE}Building ${component} for linux/amd64...${NC}"
  if ! docker buildx build \
    --platform linux/amd64 \
    --file "${PROJECT_ROOT}/${context}/${dockerfile}" \
    $TAG_ARGS \
    --push \
    --cache-from type=registry,ref=${IMAGE_NAME}:buildcache \
    --cache-to type=registry,ref=${IMAGE_NAME}:buildcache,mode=max \
    "${PROJECT_ROOT}/${context}"; then
    echo -e "${RED}  ✗ Failed to build and push $component${NC}"
    FAILED=$((FAILED + 1))
    FAILED_COMPONENTS+=("$component")
    echo ""
    continue
  fi
  
  echo -e "${GREEN}  ✓ Built and pushed $component${NC}"
  for tag in "${TAGS[@]}"; do
    echo -e "${GREEN}    - $tag${NC}"
  done
  SUCCESS=$((SUCCESS + 1))
  echo ""
done

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Build and push summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}Successfully built and pushed: $SUCCESS${NC}"
if [ $FAILED -gt 0 ]; then
  echo -e "${RED}Failed: $FAILED${NC}"
  echo -e "${RED}Failed components: ${FAILED_COMPONENTS[*]}${NC}"
fi
echo ""

if [ $FAILED -eq 0 ]; then
  echo -e "${GREEN}All images built and pushed successfully!${NC}"
  echo -e "${BLUE}Version: $VERSION${NC}"
  if [ -n "$SHORT_SHA" ]; then
    echo -e "${BLUE}Commit SHA: $SHORT_SHA${NC}"
  fi
  exit 0
else
  echo -e "${RED}Failed to build and push $FAILED component(s)${NC}"
  exit 1
fi

