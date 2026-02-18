#!/bin/bash

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
YC_REGISTRY="${1:-}"
PREFIX="${2:-manual-test}"

# Validate YC registry is provided
if [ -z "$YC_REGISTRY" ]; then
  echo -e "${RED}ERROR: YC Container Registry ID is required${NC}"
  echo -e "${YELLOW}Usage: $0 <yc-registry-url> [prefix]${NC}"
  echo -e "${YELLOW}YC Registry format: cr.yandex/<registry-id>${NC}"
  echo -e "${YELLOW}Example: $0 cr.yandex/crp1mu03jgfvckifcqsn manual-test${NC}"
  echo -e "${YELLOW}Example: $0 cr.yandex/crp1mu03jgfvckifcqsn${NC}"
  exit 1
fi

# Generate timestamp
TIMESTAMP=$(date +%Y%m%d%H%M%S)

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Building and pushing containers to YC${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Prefix: $PREFIX${NC}"
echo -e "${BLUE}YC Registry: $YC_REGISTRY${NC}"
echo -e "${BLUE}Tag format: ${PREFIX}-v1-${TIMESTAMP}${NC}"
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

# Create buildx builder if it doesn't exist
BUILDER_NAME="agentarea-x86-builder"
if ! docker buildx inspect "$BUILDER_NAME" &> /dev/null; then
  echo -e "${BLUE}Creating buildx builder: $BUILDER_NAME${NC}"
  docker buildx create --name "$BUILDER_NAME" --use
else
  echo -e "${BLUE}Using existing buildx builder: $BUILDER_NAME${NC}"
  docker buildx use "$BUILDER_NAME"
fi

# Log in to YC Container Registry
echo -e "${BLUE}Logging into YC Container Registry...${NC}"

# Check for YC_TOKEN environment variable
if [ -z "$YC_TOKEN" ]; then
  echo -e "${RED}ERROR: YC_TOKEN environment variable is not set${NC}"
  echo -e "${YELLOW}Please set YC_TOKEN with your Yandex Cloud IAM token${NC}"
  echo -e "${YELLOW}Example: export YC_TOKEN=your-iam-token${NC}"
  exit 1
fi

if ! docker login \
    --username iam \
    --password "$YC_TOKEN" \
    "$YC_REGISTRY"; then
  echo -e "${RED}ERROR: Failed to login to YC Container Registry${NC}"
  exit 1
fi

echo ""

# Components to build and push
# Format: component|context|dockerfile
COMPONENTS=(
  "api|agentarea-platform|apps/api/Dockerfile"
  # "worker|agentarea-platform|apps/worker/Dockerfile"
  # "bootstrap|agentarea-bootstrap|Dockerfile"
  # "frontend|agentarea-webapp|Dockerfile"
  # "mcp-manager|agentarea-mcp-manager|Dockerfile"
)

FAILED=0
SUCCESS=0

for component_info in "${COMPONENTS[@]}"; do
  IFS='|' read -r component context dockerfile <<< "$component_info"
  
  IMAGE_NAME="agentarea/agentarea-${component}"
  YC_IMAGE="${YC_REGISTRY}/${IMAGE_NAME}"
  # Tag format: {prefix}-v1-{timestamp}
  TEST_TAG="${PREFIX}-v1-${TIMESTAMP}"
  TEST_TAG_FULL="${YC_IMAGE}:${TEST_TAG}"
  LATEST_TAG_FULL="${YC_IMAGE}:latest"
  
  echo -e "${BLUE}========================================${NC}"
  echo -e "${BLUE}Processing: $component${NC}"
  echo -e "${BLUE}Context: $context${NC}"
  echo -e "${BLUE}Dockerfile: $dockerfile${NC}"
  echo -e "${BLUE}Image: $YC_IMAGE${NC}"
  echo -e "${BLUE}Test Tag: $TEST_TAG${NC}"
  echo ""
  
  # Build the image
  echo -e "${BLUE}Building ${component} for linux/amd64...${NC}"
  if ! docker buildx build \
    --platform linux/amd64 \
    --file "${PROJECT_ROOT}/${context}/${dockerfile}" \
    --tag "$TEST_TAG_FULL" \
    --tag "$LATEST_TAG_FULL" \
    --push \
    "${PROJECT_ROOT}/${context}"; then
    echo -e "${RED}  ✗ Failed to build $component${NC}"
    FAILED=$((FAILED + 1))
    echo ""
    continue
  fi
  
  echo -e "${GREEN}  ✓ Built and pushed $component${NC}"
  echo -e "${GREEN}    - $TEST_TAG_FULL${NC}"
  echo -e "${GREEN}    - $LATEST_TAG_FULL${NC}"
  SUCCESS=$((SUCCESS + 1))
  echo ""
done

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Build and push summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}Successfully built and pushed: $SUCCESS${NC}"
if [ $FAILED -gt 0 ]; then
  echo -e "${RED}Failed: $FAILED${NC}"
fi
echo ""

if [ $FAILED -eq 0 ]; then
  echo -e "${GREEN}All images built and pushed successfully!${NC}"
  echo -e "${BLUE}Tag format: ${PREFIX}-v1-${TIMESTAMP}${NC}"
  exit 0
else
  echo -e "${RED}Failed to build and push $FAILED component(s)${NC}"
  exit 1
fi

