#!/bin/bash
set -e

REGISTRY="zot-registry.tailfdd2bf.ts.net/agentarea"

echo "=== Building and pushing all services to staging ==="

# API
echo "[1/4] Building agentarea-api..."
docker build --platform linux/amd64 \
  -t $REGISTRY/agentarea-api:latest \
  -t $REGISTRY/agentarea-api:staging-rc \
  -f agentarea-platform/apps/api/Dockerfile agentarea-platform/
docker push $REGISTRY/agentarea-api:latest
docker push $REGISTRY/agentarea-api:staging-rc

# Frontend
echo "[2/4] Building agentarea-frontend..."
docker build --platform linux/amd64 \
  -t $REGISTRY/agentarea-frontend:latest \
  -t $REGISTRY/agentarea-frontend:staging-rc \
  -f agentarea-webapp/Dockerfile agentarea-webapp/
docker push $REGISTRY/agentarea-frontend:latest
docker push $REGISTRY/agentarea-frontend:staging-rc

# Worker
echo "[3/4] Building agentarea-worker..."
docker build --platform linux/amd64 \
  -t $REGISTRY/agentarea-worker:latest \
  -t $REGISTRY/agentarea-worker:staging-rc \
  -f agentarea-platform/apps/worker/Dockerfile agentarea-platform/
docker push $REGISTRY/agentarea-worker:latest
docker push $REGISTRY/agentarea-worker:staging-rc

# MCP Manager
echo "[4/4] Building agentarea-mcp-manager..."
docker build --platform linux/amd64 \
  -t $REGISTRY/agentarea-mcp-manager:latest \
  -t $REGISTRY/agentarea-mcp-manager:staging-rc \
  -f agentarea-mcp-manager/Dockerfile agentarea-mcp-manager/
docker push $REGISTRY/agentarea-mcp-manager:latest
docker push $REGISTRY/agentarea-mcp-manager:staging-rc

echo ""
echo "=== Verifying pushes ==="
for svc in agentarea-api agentarea-frontend agentarea-worker agentarea-mcp-manager; do
  echo -n "$svc: "
  curl -s "$REGISTRY/$svc/tags/list" | grep -o '"staging-rc"' > /dev/null && echo "OK" || echo "FAILED"
done

echo ""
echo "=== Restarting deployments ==="
kubectl rollout restart deployment agentarea-app-staging-api \
  -n agentarea-staging --context do-nyc3-agentarea-prod
kubectl rollout restart deployment agentarea-app-staging-frontend \
  -n agentarea-staging --context do-nyc3-agentarea-prod
kubectl rollout restart deployment agentarea-app-staging-worker \
  -n agentarea-staging --context do-nyc3-agentarea-prod
kubectl rollout restart deployment agentarea-app-staging-mcp-manager \
  -n agentarea-staging --context do-nyc3-agentarea-prod

echo ""
echo "=== Done ==="
