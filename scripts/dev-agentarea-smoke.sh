#!/usr/bin/env bash
set -euo pipefail

NS=${AGENTAREA_NAMESPACE:-agentarea-mcp-test}
GATEWAY_NS=${ENVOY_GATEWAY_NAMESPACE:-envoy-gateway-system}
GATEWAY_HOST=${MCP_GATEWAY_HOST:-mcp.agentarea.local}
RUN_ID=${RUN_ID:-$(date +%H%M%S)}
MCP_ID="tilt-smoke-${RUN_ID}"

cleanup() {
  kubectl run "aa-clean-${RUN_ID}" --rm -i --restart=Never \
    --image=curlimages/curl:8.8.0 -n "${NS}" -- \
    curl -sS -X DELETE "http://agentarea-mcp-manager/instances/${MCP_ID}" >/dev/null 2>&1 || true
  kubectl delete httproute -n "${NS}" "mcp-${MCP_ID}" --ignore-not-found=true >/dev/null 2>&1 || true
}
trap cleanup EXIT

kcurl() {
  local name=$1
  shift
  kubectl run "${name}-${RUN_ID}" --rm -i --restart=Never \
    --image=curlimages/curl:8.8.0 -n "${NS}" -- "$@"
}

echo "Checking mcp-manager health"
kcurl aa-health curl -fsS "http://agentarea-mcp-manager/health" >/dev/null

echo "Creating MCP ${MCP_ID}"
kcurl aa-mcp-create curl -fsS -X POST "http://agentarea-mcp-manager/instances" \
  -H "Content-Type: application/json" \
  -d "{\"instance_id\":\"${MCP_ID}\",\"name\":\"${MCP_ID}\",\"service_name\":\"${MCP_ID}\",\"image\":\"hashicorp/http-echo:1.0\",\"port\":5678,\"workspace_id\":\"ws-tilt-smoke\"}" >/dev/null

kubectl rollout status "deployment/mcp-${MCP_ID}" -n "${NS}" --timeout=90s

for _ in $(seq 1 30); do
  ROUTE_STATUS=$(kubectl get httproute "mcp-${MCP_ID}" -n "${NS}" \
    -o jsonpath='{range .status.parents[*].conditions[*]}{.type}={.status}:{.reason}{"\n"}{end}' 2>/dev/null || true)
  if echo "${ROUTE_STATUS}" | grep -q 'Accepted=True:Accepted' &&
     echo "${ROUTE_STATUS}" | grep -q 'ResolvedRefs=True:ResolvedRefs'; then
    break
  fi
  sleep 1
done
echo "${ROUTE_STATUS}" | grep -q 'Accepted=True:Accepted'
echo "${ROUTE_STATUS}" | grep -q 'ResolvedRefs=True:ResolvedRefs'

GATEWAY_ADDR=$(kubectl get gateway envoy-gateway -n "${GATEWAY_NS}" -o jsonpath='{.status.addresses[0].value}')
echo "Checking Gateway at ${GATEWAY_ADDR}"
curl -fsS -H "Host: ${GATEWAY_HOST}" "http://${GATEWAY_ADDR}/mcp/${MCP_ID}" | grep -q 'hello-world'

echo "Deleting MCP ${MCP_ID}"
kcurl aa-mcp-delete curl -fsS -X DELETE "http://agentarea-mcp-manager/instances/${MCP_ID}" >/dev/null
sleep 3
if kubectl get httproute -n "${NS}" "mcp-${MCP_ID}" >/dev/null 2>&1; then
  echo "HTTPRoute mcp-${MCP_ID} still exists after delete" >&2
  exit 1
fi

echo "AgentArea dev smoke passed"
