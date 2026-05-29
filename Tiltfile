kube_context = os.getenv("AGENTAREA_KUBE_CONTEXT", "agentarea-dev-timeweb")
namespace = os.getenv("AGENTAREA_NAMESPACE", "agentarea")
push_registry = os.getenv("AGENTAREA_REGISTRY", "agentarea-ru.registry.twcstorage.ru")
cluster_registry = os.getenv("AGENTAREA_CLUSTER_REGISTRY", push_registry)

allow_k8s_contexts(kube_context)
default_registry(push_registry, host_from_cluster=cluster_registry)

k8s_yaml(local(
    "helm repo add valkey https://valkey.io/valkey-helm/ >/dev/null 2>&1 || true && "
    + "helm dependency build charts/agentarea >/dev/null && "
    + "helm template agentarea charts/agentarea "
    + "--namespace " + namespace + " "
    + "-f deploy/tilt/timeweb-dev-values.yaml"
))

docker_build(
    "agentarea/agentarea-api",
    "agentarea-platform",
    dockerfile="agentarea-platform/apps/api/Dockerfile",
    live_update=[
        sync("agentarea-platform/apps/api", "/app/apps/api"),
        sync("agentarea-platform/libs", "/app/libs"),
        restart_container(),
    ],
)

docker_build(
    "agentarea/agentarea-worker",
    "agentarea-platform",
    dockerfile="agentarea-platform/apps/worker/Dockerfile",
    live_update=[
        sync("agentarea-platform/apps/worker", "/app/apps/worker"),
        sync("agentarea-platform/libs", "/app/libs"),
        restart_container(),
    ],
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
        restart_container(),
    ],
)

k8s_resource("agentarea-backend", port_forwards=8000)
k8s_resource("agentarea-frontend", port_forwards=3000)
k8s_resource("agentarea-mcp-manager")
k8s_resource("agentarea-worker")
