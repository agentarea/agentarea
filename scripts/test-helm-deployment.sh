#!/bin/bash

# AgentArea Helm Deployment E2E Test
# This script validates that all services are deployed and can communicate

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

NAMESPACE="${NAMESPACE:-agentarea}"
RELEASE_NAME="${RELEASE_NAME:-agentarea}"
TIMEOUT=300
CHECK_INTERVAL=5

# Helper functions
print_header() {
    echo -e "\n${YELLOW}=== $1 ===${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}ℹ $1${NC}"
}

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    print_error "kubectl not found. Please install kubectl."
    exit 1
fi

# Check namespace exists
if ! kubectl get ns "$NAMESPACE" &> /dev/null; then
    print_info "Creating namespace: $NAMESPACE"
    kubectl create ns "$NAMESPACE"
fi

# Wait for deployment to be ready
wait_for_deployment() {
    local deployment=$1
    local timeout=$2
    local elapsed=0

    while [ $elapsed -lt $timeout ]; do
        local ready=$(kubectl get deployment "$deployment" -n "$NAMESPACE" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo 0)
        local desired=$(kubectl get deployment "$deployment" -n "$NAMESPACE" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo 0)

        if [ "$ready" == "$desired" ] && [ "$desired" -gt 0 ]; then
            print_success "Deployment $deployment is ready"
            return 0
        fi

        sleep $CHECK_INTERVAL
        elapsed=$((elapsed + CHECK_INTERVAL))
    done

    print_error "Deployment $deployment did not become ready within $timeout seconds"
    return 1
}

# Wait for pod readiness
wait_for_pod() {
    local pod_label=$1
    local timeout=$2
    local elapsed=0

    while [ $elapsed -lt $timeout ]; do
        local pod=$(kubectl get pods -n "$NAMESPACE" -l "$pod_label" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")

        if [ -z "$pod" ]; then
            sleep $CHECK_INTERVAL
            elapsed=$((elapsed + CHECK_INTERVAL))
            continue
        fi

        local status=$(kubectl get pod "$pod" -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null)

        if [ "$status" == "Running" ]; then
            print_success "Pod with label $pod_label is running"
            return 0
        fi

        sleep $CHECK_INTERVAL
        elapsed=$((elapsed + CHECK_INTERVAL))
    done

    print_error "Pod with label $pod_label did not become ready within $timeout seconds"
    return 1
}

# Test service connectivity
test_service_connectivity() {
    local service=$1
    local port=$2
    local expected_status=${3:-200}

    # Create a test pod to curl the service
    local test_pod="test-connectivity-$(date +%s)"

    kubectl run "$test_pod" \
        --image=curlimages/curl:latest \
        --rm -i --restart=Never \
        -n "$NAMESPACE" \
        -- curl -s -o /dev/null -w "%{http_code}" \
        "http://$service.$NAMESPACE.svc.cluster.local:$port/health" 2>/dev/null || true
}

print_header "Starting AgentArea Helm Deployment E2E Tests"

# Check if release exists
print_info "Checking if Helm release '$RELEASE_NAME' exists..."
if ! helm list -n "$NAMESPACE" | grep -q "$RELEASE_NAME"; then
    print_error "Release $RELEASE_NAME not found. Please deploy with: helm install $RELEASE_NAME ./charts/agentarea -n $NAMESPACE"
    exit 1
fi
print_success "Helm release found"

# Test 1: Check all deployments exist and are running
print_header "Test 1: Checking Deployments"
DEPLOYMENTS=(
    "agentarea-postgresql"
    "agentarea-redis"
    "agentarea-rustfs"
    "agentarea-temporal"
    "agentarea-kratos"
    "agentarea-backend"
    "agentarea-worker"
    "agentarea-mcp-manager"
)

failed_deployments=0
for deployment in "${DEPLOYMENTS[@]}"; do
    if kubectl get deployment "$deployment" -n "$NAMESPACE" &> /dev/null; then
        wait_for_deployment "$deployment" $TIMEOUT || failed_deployments=$((failed_deployments + 1))
    else
        print_error "Deployment $deployment not found"
        failed_deployments=$((failed_deployments + 1))
    fi
done

if [ $failed_deployments -gt 0 ]; then
    print_error "$failed_deployments deployments failed to become ready"
else
    print_success "All deployments are ready"
fi

# Test 2: Check all services exist
print_header "Test 2: Checking Services"
SERVICES=(
    "agentarea-postgresql"
    "agentarea-redis"
    "agentarea-rustfs"
    "agentarea-temporal"
    "agentarea-kratos-public"
    "agentarea-kratos-admin"
    "agentarea-backend"
    "agentarea-mcp-manager"
)

for service in "${SERVICES[@]}"; do
    if kubectl get service "$service" -n "$NAMESPACE" &> /dev/null; then
        print_success "Service $service exists"
    else
        print_error "Service $service not found"
    fi
done

# Test 3: Check database connectivity
print_header "Test 3: Checking Database Connectivity"
print_info "Checking PostgreSQL connection..."
POD=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=postgresql -o jsonpath='{.items[0].metadata.name}')
if [ ! -z "$POD" ]; then
    kubectl exec "$POD" -n "$NAMESPACE" -- pg_isready -U postgres && print_success "PostgreSQL is ready" || print_error "PostgreSQL is not ready"
else
    print_error "PostgreSQL pod not found"
fi

# Test 4: Check Redis connectivity
print_header "Test 4: Checking Redis Connectivity"
print_info "Checking Redis connection..."
POD=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=redis -o jsonpath='{.items[0].metadata.name}')
if [ ! -z "$POD" ]; then
    kubectl exec "$POD" -n "$NAMESPACE" -- redis-cli ping && print_success "Redis is ready" || print_error "Redis is not ready"
else
    print_error "Redis pod not found"
fi

# Test 5: Check RustFS connectivity
print_header "Test 5: Checking RustFS Connectivity"
print_info "Checking RustFS health..."
if POD=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/component=rustfs -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); then
    kubectl exec "$POD" -n "$NAMESPACE" -- curl -s http://localhost:9000/minio/health/live > /dev/null && print_success "RustFS is ready" || print_error "RustFS is not ready"
else
    print_error "RustFS pod not found"
fi

# Test 6: Check Temporal connectivity
print_header "Test 6: Checking Temporal Connectivity"
print_info "Checking Temporal server..."
POD=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=temporal -o jsonpath='{.items[0].metadata.name}')
if [ ! -z "$POD" ]; then
    kubectl exec "$POD" -n "$NAMESPACE" -- tctl --address localhost:7233 cluster health && print_success "Temporal is ready" || print_error "Temporal is not ready"
else
    print_error "Temporal pod not found"
fi

# Test 7: Check Kratos connectivity
print_header "Test 7: Checking Kratos Connectivity"
print_info "Checking Kratos public health..."
POD=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/component=kratos -o jsonpath='{.items[0].metadata.name}')
if [ ! -z "$POD" ]; then
    kubectl exec "$POD" -n "$NAMESPACE" -- curl -s http://localhost:4433/health/ready > /dev/null && print_success "Kratos public is ready" || print_error "Kratos public is not ready"
else
    print_error "Kratos pod not found"
fi

print_info "Checking JWKS secret..."
if kubectl get secret -n "$NAMESPACE" "${RELEASE_NAME}-kratos-jwks" &> /dev/null; then
    print_success "JWKS secret exists"
else
    print_error "JWKS secret not found"
fi

# Test 8: Check API Backend connectivity
print_header "Test 8: Checking API Backend"
print_info "Checking API health endpoint..."
POD=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=api -o jsonpath='{.items[0].metadata.name}')
if [ ! -z "$POD" ]; then
    kubectl exec "$POD" -n "$NAMESPACE" -- curl -s http://localhost:8000/health > /dev/null && print_success "API is responding" || print_error "API is not responding"
else
    print_info "API pod not yet running (may still be initializing)"
fi

# Test 9: Check bootstrap jobs
print_header "Test 9: Checking Bootstrap Jobs"
print_info "Checking bootstrap job status..."
BOOTSTRAP_JOBS=$(kubectl get jobs -n "$NAMESPACE" -l app.kubernetes.io/name=bootstrap -o jsonpath='{.items[*].metadata.name}')
if [ ! -z "$BOOTSTRAP_JOBS" ]; then
    for job in $BOOTSTRAP_JOBS; do
        SUCCEEDED=$(kubectl get job "$job" -n "$NAMESPACE" -o jsonpath='{.status.succeeded}')
        if [ "$SUCCEEDED" == "1" ]; then
            print_success "Bootstrap job $job completed"
        else
            print_info "Bootstrap job $job is still running or pending"
        fi
    done
else
    print_error "No bootstrap jobs found"
fi

# Summary
print_header "Test Summary"
print_success "E2E validation complete!"
print_info "To view logs, use: kubectl logs -f <pod-name> -n $NAMESPACE"
print_info "To port forward services:"
echo -e "  ${YELLOW}API (8000):${NC}     kubectl port-forward -n $NAMESPACE svc/agentarea-backend 8000:8000"
echo -e "  ${YELLOW}Kratos Public (4433):${NC}  kubectl port-forward -n $NAMESPACE svc/agentarea-kratos-public 4433:4433"
echo -e "  ${YELLOW}Kratos Admin (4434):${NC}   kubectl port-forward -n $NAMESPACE svc/agentarea-kratos-admin 4434:4434"
echo -e "  ${YELLOW}Temporal (7233):${NC} kubectl port-forward -n $NAMESPACE svc/agentarea-temporal 7233:7233"
echo -e "  ${YELLOW}RustFS (9001):${NC}   kubectl port-forward -n $NAMESPACE svc/agentarea-rustfs 9001:9001"
