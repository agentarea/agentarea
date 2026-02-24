# Implementation Plan: Kata + Warm Pool for MCP

## Phase 1: Cluster Setup (1-2 days)

### 1.1 Install Kata Containers

```bash
# Install Kata on all nodes
kubectl apply -f https://raw.githubusercontent.com/kata-containers/kata-containers/main/tools/packaging/kata-deploy/kata-deploy.yaml

# Verify runtime class created
kubectl get runtimeclass
# NAME        HANDLER     AGE
# kata-qemu   kata-qemu   1m
```

### 1.2 Verify Node Support

```bash
# Check nodes support virtualization
kubectl get nodes -o json | jq '.items[].status.allocatable'
# Should show: devices.kubevirt.io/kvm: "110"
```

## Phase 2: Warm Pool DaemonSet (2-3 days)

### 2.1 Create Generic MCP Runner Image

```dockerfile
# Dockerfile.mcp-runner
FROM alpine:3.19

# Install base dependencies
RUN apk add --no-cache \
    ca-certificates \
    curl \
    tar \
    gzip \
    iptables

# Install containerd client for image pulling
COPY --from=ghcr.io/containerd/containerd:v1.7.0 /usr/bin/ctr /usr/local/bin/ctr

# Install activation service
COPY activation-service /usr/local/bin/activation-service
COPY activate.sh /usr/local/bin/activate

# Create directories
RUN mkdir -p /app/mcp /var/cache/mcp-images /tmp/overlay

# Port for activation API
EXPOSE 8080
# Port for MCP protocol
EXPOSE 3000

# Wait for assignment
CMD ["/usr/local/bin/activation-service", "--mode=wait"]
```

### 2.2 Activation Service (Go)

```go
// cmd/activation-service/main.go
package main

import (
    "context"
    "flag"
    "log"
    "net/http"
    "os"
    "os/exec"
    "syscall"
)

type ActivationServer struct {
    status string // "waiting" | "activating" | "ready"
    config *MCPConfig
}

type ActivateRequest struct {
    MCPImage     string            `json:"mcp_image"`
    MCPImageHash string            `json:"mcp_image_hash"`
    Env          map[string]string `json:"env"`
    Config       json.RawMessage   `json:"config"`
}

func (s *ActivationServer) Activate(w http.ResponseWriter, r *http.Request) {
    if s.status != "waiting" {
        http.Error(w, `{"error": "pod already assigned"}`, http.StatusConflict)
        return
    }
    
    var req ActivateRequest
    if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
        http.Error(w, err.Error(), http.StatusBadRequest)
        return
    }
    
    s.status = "activating"
    
    // Download image if not cached
    imagePath := "/var/cache/mcp-images/" + req.MCPImageHash + ".tar"
    if _, err := os.Stat(imagePath); os.IsNotExist(err) {
        if err := downloadImage(req.MCPImage, imagePath); err != nil {
            s.status = "waiting"
            http.Error(w, err.Error(), http.StatusInternalServerError)
            return
        }
    }
    
    // Extract and mount
    if err := s.activateMCP(imagePath, req.Env); err != nil {
        s.status = "waiting"
        http.Error(w, err.Error(), http.StatusInternalServerError)
        return
    }
    
    s.status = "ready"
    
    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(map[string]string{
        "status": "ready",
        "mcp_port": "3000",
    })
}

func (s *ActivationServer) activateMCP(imagePath string, env map[string]string) error {
    // Extract image
    extractDir := "/app/mcp-extracted"
    if err := os.MkdirAll(extractDir, 0755); err != nil {
        return err
    }
    
    cmd := exec.Command("tar", "-xzf", imagePath, "-C", extractDir)
    if err := cmd.Run(); err != nil {
        return fmt.Errorf("failed to extract: %w", err)
    }
    
    // Overlay mount
    lowerDir := "/app/mcp-base"      // base runner files
    upperDir := extractDir
    workDir := "/tmp/overlay-work"
    mergeDir := "/app/mcp"
    
    if err := os.MkdirAll(workDir, 0755); err != nil {
        return err
    }
    
    // Perform overlay mount
    mountCmd := exec.Command("mount", "-t", "overlay", "overlay",
        "-o", fmt.Sprintf("lowerdir=%s,upperdir=%s,workdir=%s", lowerDir, upperDir, workDir),
        mergeDir)
    if err := mountCmd.Run(); err != nil {
        return fmt.Errorf("failed to mount overlay: %w", err)
    }
    
    // Set environment
    for k, v := range env {
        os.Setenv(k, v)
    }
    
    // Start MCP process
    mcpCmd := exec.Command("/app/mcp/start.sh")
    mcpCmd.Dir = "/app/mcp"
    mcpCmd.SysProcAttr = &syscall.SysProcAttr{
        Setpgid: true,
    }
    
    if err := mcpCmd.Start(); err != nil {
        return fmt.Errorf("failed to start MCP: %w", err)
    }
    
    // Wait for MCP to be ready (health check)
    if err := waitForMCPReady(10 * time.Second); err != nil {
        mcpCmd.Process.Kill()
        return fmt.Errorf("MCP failed to start: %w", err)
    }
    
    return nil
}

func main() {
    mode := flag.String("mode", "wait", "Mode: wait or standalone")
    flag.Parse()
    
    server := &ActivationServer{status: "waiting"}
    
    http.HandleFunc("/activate", server.Activate)
    http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
        json.NewEncoder(w).Encode(map[string]string{
            "status": server.status,
        })
    })
    
    log.Println("Activation service starting on :8080")
    log.Fatal(http.ListenAndServe(":8080", nil))
}
```

### 2.3 Warm Pool DaemonSet

```yaml
# deploy/warm-pool.yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: mcp-warm-pool
  namespace: mcp-system
spec:
  selector:
    matchLabels:
      app: mcp-warm-pool
  template:
    metadata:
      labels:
        app: mcp-warm-pool
        mcp.agentarea.io/role: "warm-pool"
        mcp.agentarea.io/status: "waiting"
    spec:
      runtimeClassName: kata-qemu  # Run in Kata VMs
      hostNetwork: false
      containers:
        - name: warm-pod
          image: agentarea/mcp-runner:latest
          imagePullPolicy: Always
          ports:
            - name: activation
              containerPort: 8080
              protocol: TCP
            - name: mcp
              containerPort: 3000
              protocol: TCP
          resources:
            requests:
              memory: "128Mi"
              cpu: "100m"
            limits:
              memory: "512Mi"
              cpu: "500m"
          securityContext:
            allowPrivilegeEscalation: true  # Required for overlay mount
            capabilities:
              add:
                - SYS_ADMIN  # Required for mount
          volumeMounts:
            - name: image-cache
              mountPath: /var/cache/mcp-images
            - name: overlay-tmp
              mountPath: /tmp
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 2
            periodSeconds: 5
      volumes:
        - name: image-cache
          hostPath:
            path: /var/lib/mcp-image-cache
            type: DirectoryOrCreate
        - name: overlay-tmp
          emptyDir: {}
      # Tolerations for running on all nodes
      tolerations:
        - operator: Exists
```

### 2.4 ConfigMap for Pool Configuration

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: mcp-warm-pool-config
  namespace: mcp-system
data:
  pool-size: "10"  # Pods per node
  activation-timeout: "30s"
  image-cache-size: "10Gi"
  default-mcp-port: "3000"
```

## Phase 3: MCP Manager Changes (3-4 days)

### 3.1 Warm Pool Client

```go
// internal/warmpool/client.go
package warmpool

import (
    "context"
    "fmt"
    "net/http"
    "time"

    corev1 "k8s.io/api/core/v1"
    metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
    "k8s.io/client-go/kubernetes"
)

type Client struct {
    client    kubernetes.Interface
    namespace string
    timeout   time.Duration
}

func New(client kubernetes.Interface, namespace string) *Client {
    return &Client{
        client:    client,
        namespace: namespace,
        timeout:   30 * time.Second,
    }
}

// FindAvailablePod finds a warm pod that's waiting for assignment
func (c *Client) FindAvailablePod(ctx context.Context) (*corev1.Pod, error) {
    pods, err := c.client.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
        LabelSelector: "mcp.agentarea.io/role=warm-pool,mcp.agentarea.io/status=waiting",
        Limit:         1,
    })
    if err != nil {
        return nil, err
    }
    
    if len(pods.Items) == 0 {
        return nil, fmt.Errorf("no warm pods available")
    }
    
    return &pods.Items[0], nil
}

// AssignPod marks a pod as assigned to a specific MCP
func (c *Client) AssignPod(ctx context.Context, pod *corev1.Pod, instanceID, userID, mcpName string) (*corev1.Pod, error) {
    if pod.Labels == nil {
        pod.Labels = make(map[string]string)
    }
    
    pod.Labels["mcp.agentarea.io/status"] = "activating"
    pod.Labels["mcp.agentarea.io/instance-id"] = instanceID
    pod.Labels["mcp.agentarea.io/user-id"] = userID
    pod.Labels["mcp.agentarea.io/mcp-name"] = mcpName
    
    return c.client.CoreV1().Pods(c.namespace).Update(ctx, pod, metav1.UpdateOptions{})
}

// ActivatePod calls the activation endpoint inside the pod
func (c *Client) ActivatePod(ctx context.Context, pod *corev1.Pod, req ActivationRequest) error {
    podIP := pod.Status.PodIP
    if podIP == "" {
        return fmt.Errorf("pod has no IP")
    }
    
    url := fmt.Sprintf("http://%s:8080/activate", podIP)
    
    body, err := json.Marshal(req)
    if err != nil {
        return err
    }
    
    httpReq, err := http.NewRequestWithContext(ctx, "POST", url, bytes.NewReader(body))
    if err != nil {
        return err
    }
    httpReq.Header.Set("Content-Type", "application/json")
    
    client := &http.Client{Timeout: c.timeout}
    resp, err := client.Do(httpReq)
    if err != nil {
        return fmt.Errorf("activation failed: %w", err)
    }
    defer resp.Body.Close()
    
    if resp.StatusCode != http.StatusOK {
        return fmt.Errorf("activation returned %d", resp.StatusCode)
    }
    
    return nil
}

// MarkReady marks pod as ready for traffic
func (c *Client) MarkReady(ctx context.Context, pod *corev1.Pod) (*corev1.Pod, error) {
    pod.Labels["mcp.agentarea.io/status"] = "ready"
    return c.client.CoreV1().Pods(c.namespace).Update(ctx, pod, metav1.UpdateOptions{})
}

// ReturnToPool returns a pod to the waiting pool
func (c *Client) ReturnToPool(ctx context.Context, pod *corev1.Pod) error {
    // Remove assignment labels
    delete(pod.Labels, "mcp.agentarea.io/status")
    delete(pod.Labels, "mcp.agentarea.io/instance-id")
    delete(pod.Labels, "mcp.agentarea.io/user-id")
    delete(pod.Labels, "mcp.agentarea.io/mcp-name")
    
    pod.Labels["mcp.agentarea.io/status"] = "waiting"
    
    _, err := c.client.CoreV1().Pods(c.namespace).Update(ctx, pod, metav1.UpdateOptions{})
    return err
}
```

### 3.2 Integration with MCP Creation

```go
// internal/providers/kubernetes_provider.go

func (p *KubernetesProvider) CreateWithWarmPool(ctx context.Context, instance *models.MCPServerInstance) error {
    // 1. Try to use warm pool
    pod, err := p.warmPool.FindAvailablePod(ctx)
    if err == nil {
        // Warm pod available - use fast path
        return p.activateWithWarmPool(ctx, instance, pod)
    }
    
    // 2. No warm pods - fall back to cold start
    p.logger.Warn("No warm pods available, using cold start", "instance", instance.Name)
    return p.createColdStart(ctx, instance)
}

func (p *KubernetesProvider) activateWithWarmPool(ctx context.Context, instance *models.MCPServerInstance, pod *corev1.Pod) error {
    // 1. Mark pod as assigned
    pod, err := p.warmPool.AssignPod(ctx, pod, instance.ID, instance.UserID, instance.Name)
    if err != nil {
        return fmt.Errorf("failed to assign pod: %w", err)
    }
    
    // 2. Activate MCP inside the pod
    activationReq := warmpool.ActivationRequest{
        MCPImage:     instance.Image,
        MCPImageHash: hashImage(instance.Image),
        Env:          instance.Environment,
        Config:       instance.Config,
    }
    
    if err := p.warmPool.ActivatePod(ctx, pod, activationReq); err != nil {
        // Return pod to pool
        p.warmPool.ReturnToPool(ctx, pod)
        return fmt.Errorf("activation failed: %w", err)
    }
    
    // 3. Mark as ready
    pod, err = p.warmPool.MarkReady(ctx, pod)
    if err != nil {
        return fmt.Errorf("failed to mark ready: %w", err)
    }
    
    // 4. Create or update Service to point to this pod
    if err := p.createServiceForPod(ctx, instance, pod); err != nil {
        return fmt.Errorf("failed to create service: %w", err)
    }
    
    // 5. Create HTTPRoute
    if err := p.createHTTPRoute(ctx, instance); err != nil {
        return fmt.Errorf("failed to create HTTPRoute: %w", err)
    }
    
    return nil
}
```

## Phase 4: Image Caching (1-2 days)

### 4.1 Node-Level Image Cache

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: mcp-image-warmer
  namespace: mcp-system
spec:
  template:
    spec:
      hostPID: true
      hostNetwork: true
      containers:
        - name: warmer
          image: alpine:3.19
          command:
            - /bin/sh
            - -c
            - |
              # Install tools
              apk add --no-cache curl jq
              
              # Watch for image pull requests
              while true; do
                # Check API for new MCP images
                IMAGES=$(curl -s http://mcp-manager:8080/api/v1/images/to-prefetch)
                
                for image in $(echo $IMAGES | jq -r '.[]'); do
                  # Check if already cached
                  if ! ctr images check "${image}" > /dev/null 2>&1; then
                    echo "Prefetching: ${image}"
                    ctr images pull "${image}" || true
                  fi
                done
                
                sleep 60
              done
          volumeMounts:
            - name: containerd-sock
              mountPath: /run/containerd/containerd.sock
            - name: image-cache
              mountPath: /var/lib/containerd
      volumes:
        - name: containerd-sock
          hostPath:
            path: /run/containerd/containerd.sock
        - name: image-cache
          hostPath:
            path: /var/lib/containerd
```

## Phase 5: Monitoring (1 day)

### 5.1 Metrics

```go
// Metrics to expose
var (
    warmPoolSize = prometheus.NewGaugeVec(
        prometheus.GaugeOpts{
            Name: "mcp_warm_pool_size",
            Help: "Number of pods in warm pool",
        },
        []string{"node", "status"},
    )
    
    activationDuration = prometheus.NewHistogramVec(
        prometheus.HistogramOpts{
            Name:    "mcp_activation_duration_seconds",
            Help:    "Time to activate MCP from warm pool",
            Buckets: []float64{0.1, 0.25, 0.5, 1, 2, 5, 10},
        },
        []string{"result"},
    )
    
    activationFailures = prometheus.NewCounterVec(
        prometheus.CounterOpts{
            Name: "mcp_activation_failures_total",
            Help: "Total activation failures",
        },
        []string{"reason"},
    )
)
```

## Phase 6: Testing (2-3 days)

### 6.1 Test Scenarios

```bash
# Test 1: Fast activation from warm pool
curl -X POST http://mcp-manager:8080/instances \
  -d '{"name": "test-mcp", "image": "nginx:alpine"}'
# Expected: <500ms response, pod activated from warm pool

# Test 2: Fallback to cold start (no warm pods)
# Scale warm pool to 0, then create MCP
# Expected: 8-15s response, new pod created

# Test 3: Concurrent activations
# Create 20 MCPs simultaneously
# Expected: First 10 fast (<500ms), rest fallback or queue

# Test 4: Kata isolation
kubectl exec -it mcp-test-mcp -- cat /proc/1/cgroup
# Expected: Shows kata-specific paths
```

## Summary: What We Need

| Component | Effort | Status |
|-----------|--------|--------|
| Kata installation on cluster | 1-2 days | Cluster admin task |
| MCP runner image | 1 day | New Dockerfile |
| Activation service | 2 days | Go binary in image |
| Warm pool DaemonSet | 1 day | K8s manifest |
| MCP Manager warm pool client | 2 days | New package |
| Image caching | 1 day | DaemonSet |
| Monitoring | 1 day | Metrics |
| Testing | 2-3 days | Integration tests |
| **Total** | **~2 weeks** | |

## Dependencies

1. **Kata Containers** installed on cluster nodes
2. **Nested virtualization** enabled (for cloud VMs)
3. **Containerd** with snapshotter support
4. **Sufficient node memory** for warm pool (2-3GB per node)

## Rollout Strategy

1. **Week 1**: Cluster setup + warm pool DaemonSet
2. **Week 2**: MCP Manager integration + testing
3. **Gradual**: Enable per-node, monitor metrics
