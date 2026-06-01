#!/usr/bin/env bash
set -euo pipefail

NAMESPACE=${ENVOY_GATEWAY_NAMESPACE:-envoy-gateway-system}
RELEASE=${ENVOY_GATEWAY_RELEASE:-eg}
VERSION=${ENVOY_GATEWAY_VERSION:-v1.8.0}

kubectl get crd gateways.gateway.networking.k8s.io >/dev/null

helm template eg-crds oci://docker.io/envoyproxy/gateway-crds-helm \
  --version "${VERSION}" \
  --set crds.gatewayAPI.enabled=true \
  --set crds.gatewayAPI.channel=experimental \
  --set crds.envoyGateway.enabled=true |
  kubectl apply --server-side -f -

if ! helm status "${RELEASE}" -n "${NAMESPACE}" >/dev/null 2>&1; then
  helm install "${RELEASE}" oci://docker.io/envoyproxy/gateway-helm \
    --version "${VERSION}" \
    -n "${NAMESPACE}" \
    --create-namespace \
    --skip-crds
fi

kubectl rollout status deployment/envoy-gateway -n "${NAMESPACE}" --timeout=5m
kubectl apply -f dev/gateway.yaml
kubectl wait --timeout=3m gatewayclass/envoy-gateway --for=condition=Accepted
kubectl wait --timeout=3m -n "${NAMESPACE}" gateway/envoy-gateway --for=condition=Programmed
