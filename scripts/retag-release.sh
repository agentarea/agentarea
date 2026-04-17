#!/bin/bash

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Get the script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Read VERSION from VERSION file
if [ ! -f "$PROJECT_ROOT/VERSION" ]; then
  echo -e "${RED}ERROR: VERSION file not found at $PROJECT_ROOT/VERSION${NC}"
  exit 1
fi

VERSION=$(cat "$PROJECT_ROOT/VERSION" | tr -d '\n')
VERSION_TAG="v${VERSION}"

echo -e "${BLUE}Re-tagging Docker images for release${NC}"
echo -e "${BLUE}Version: $VERSION_TAG${NC}"

# Ask user for commit SHA (since ci.yml may not run on version bump commits)
read -p "Enter the commit SHA that was built (short or long format): " COMMIT_INPUT
COMMIT_SHA=$(git rev-parse --short=7 "$COMMIT_INPUT" 2>/dev/null)

if [ -z "$COMMIT_SHA" ]; then
  echo -e "${RED}ERROR: Could not resolve commit SHA${NC}"
  exit 1
fi

COMMIT_TAG="commit-${COMMIT_SHA}"

echo -e "${BLUE}Commit SHA: $COMMIT_SHA${NC}"
echo ""

# Components to re-tag
COMPONENTS=("api" "worker" "frontend" "operator" "mcp-manager")

# Log in to Docker Hub
echo -e "${BLUE}Logging into Docker Hub...${NC}"
docker login

echo ""
echo -e "${BLUE}Starting re-tagging process...${NC}"
echo ""

FAILED=0

for component in "${COMPONENTS[@]}"; do
  IMAGE_NAME="agentarea/agentarea-${component}"
  SOURCE_TAG="${IMAGE_NAME}:${COMMIT_TAG}"
  VERSION_IMAGE="${IMAGE_NAME}:${VERSION_TAG}"
  LATEST_IMAGE="${IMAGE_NAME}:latest"

  echo -e "${BLUE}Processing $component...${NC}"

  # Pull the image from main build
  echo -e "  Pulling ${SOURCE_TAG}..."
  if ! docker pull "$SOURCE_TAG"; then
    echo -e "${RED}  ✗ Failed to pull $SOURCE_TAG${NC}"
    FAILED=$((FAILED + 1))
    continue
  fi

  # Create version tag
  echo -e "  Tagging as ${VERSION_IMAGE}..."
  docker tag "$SOURCE_TAG" "$VERSION_IMAGE"

  # Create latest tag
  echo -e "  Tagging as ${LATEST_IMAGE}..."
  docker tag "$SOURCE_TAG" "$LATEST_IMAGE"

  # Push version tag
  echo -e "  Pushing ${VERSION_IMAGE}..."
  if ! docker push "$VERSION_IMAGE"; then
    echo -e "${RED}  ✗ Failed to push version tag${NC}"
    FAILED=$((FAILED + 1))
    continue
  fi

  # Push latest tag
  echo -e "  Pushing ${LATEST_IMAGE}..."
  if ! docker push "$LATEST_IMAGE"; then
    echo -e "${RED}  ✗ Failed to push latest tag${NC}"
    FAILED=$((FAILED + 1))
    continue
  fi

  echo -e "${GREEN}  ✓ $component re-tagged and pushed${NC}"
  echo ""
done

echo -e "${BLUE}Re-tagging process complete!${NC}"

if [ $FAILED -eq 0 ]; then
  echo -e "${GREEN}All images re-tagged successfully!${NC}"
  exit 0
else
  echo -e "${RED}Failed to re-tag $FAILED component(s)${NC}"
  exit 1
fi
