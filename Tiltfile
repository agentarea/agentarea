kube_context = os.getenv("AGENTAREA_KUBE_CONTEXT", "agentarea-dev-timeweb")
namespace = os.getenv("AGENTAREA_NAMESPACE", "agentarea")
push_registry = os.getenv("AGENTAREA_REGISTRY", "agentarea-ru.registry.twcstorage.ru")
cluster_registry = os.getenv("AGENTAREA_CLUSTER_REGISTRY", push_registry)
image_pull_secret = os.getenv("AGENTAREA_IMAGE_PULL_SECRET", "")

allow_k8s_contexts(kube_context)
default_registry(push_registry, host_from_cluster=cluster_registry)

helm_args = (
    "helm repo add valkey https://valkey.io/valkey-helm/ >/dev/null 2>&1 || true && "
    + "helm dependency build charts/agentarea >/dev/null && "
    + "helm template agentarea charts/agentarea "
    + "--namespace " + namespace + " "
    + "-f deploy/tilt/timeweb-dev-values.yaml"
)
if image_pull_secret:
    helm_args = helm_args + " --set global.image.pullSecrets[0].name=" + image_pull_secret

k8s_yaml(local(helm_args + " | python3 deploy/tilt/add-namespace.py " + namespace))

docker_build(
    "agentarea/agentarea-api",
    "agentarea-platform",
    dockerfile="agentarea-platform/apps/api/Dockerfile",
)

docker_build(
    "agentarea/agentarea-worker",
    "agentarea-platform",
    dockerfile="agentarea-platform/apps/worker/Dockerfile",
)

docker_build(
    "agentarea/agentarea-frontend",
    "agentarea-webapp",
    dockerfile="agentarea-webapp/Dockerfile.dev",
    live_update=[
        sync("agentarea-webapp/src", "/app/src"),
        sync("agentarea-webapp/messages", "/app/messages"),
        sync("agentarea-webapp/public", "/app/public"),
        sync("agentarea-webapp/packages", "/app/packages"),
        run(
            "corepack prepare pnpm@9.15.4 --activate && pnpm install",
            trigger=[
                "agentarea-webapp/package.json",
                "agentarea-webapp/pnpm-lock.yaml",
                "agentarea-webapp/pnpm-workspace.yaml",
            ],
        ),
    ],
)

docker_build(
    "agentarea/agentarea-mcp-manager",
    "agentarea-mcp-manager",
    dockerfile="agentarea-mcp-manager/Dockerfile.dev",
    target="development",
    live_update=[
        sync("agentarea-mcp-manager", "/app"),
        run("go mod download", trigger=["agentarea-mcp-manager/go.mod", "agentarea-mcp-manager/go.sum"]),
    ],
)

docker_build(
    "agentarea/agentarea-events",
    "agentarea-event-service",
    dockerfile="agentarea-event-service/Dockerfile.dev",
    live_update=[
        sync("agentarea-event-service", "/app"),
        run("go mod download", trigger=["agentarea-event-service/go.mod", "agentarea-event-service/go.sum"]),
    ],
)

k8s_resource("agentarea-backend", port_forwards=8000)
k8s_resource("agentarea-frontend", port_forwards=3000)
k8s_resource("agentarea-mcp-manager")
k8s_resource("agentarea-worker")
k8s_resource("agentarea-event-service")
