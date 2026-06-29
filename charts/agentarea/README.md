# agentarea

> AgentArea is an AI agent platform. This chart deploys the API, frontend, worker, MCP Manager, and optional dependencies.

## Usage

```bash
helm repo add agentarea https://agentarea.github.io/helm-charts
helm repo update
helm install agentarea agentarea/agentarea \
  --namespace agentarea --create-namespace
```

## Prerequisites

- Kubernetes 1.20+
- Helm 3.8+
- PV provisioner for PostgreSQL/RustFS persistence (if enabled)

## Installing with external services

If you have existing PostgreSQL, Redis or S3-compatible storage, disable bundled dependencies and set endpoints:

```yaml
postgresql:
  enabled: false
redis:
  enabled: false
rustfs:
  enabled: false

global:
  database:
    host: "db.example.com"
    port: 5432
    name: "agentarea"
  redis:
    host: "redis.example.com"
    port: 6379
  storage:
    type: "s3"
    endpoint: "https://s3.amazonaws.com"
    bucket: "agentarea-docs"
    region: "us-east-1"
```

## Parameters

The following table lists configurable parameters of the chart and their default values.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| serviceAccount.create | bool | `true` |  |
| serviceAccount.annotations | object | `{}` |  |
| serviceAccount.name | string | `"agentarea"` |  |
| nameOverride | string | `""` |  |
| fullnameOverride | string | `""` |  |
| global.edition | string | `"community"` |  |
| global.version | string | `"0.0.3"` |  |
| global.cluster.type | string | `"kubernetes"` |  |
| global.cluster.name | string | `"agentarea"` |  |
| global.deploymentEnv | string | `"production"` |  |
| global.image.pullPolicy | string | `"IfNotPresent"` |  |
| global.image.registry | string | `""` |  |
| global.image.pullSecrets | list | `[]` |  |
| global.serviceAccountName | string | `"agentarea"` |  |
| global.secrets.postgresql | string | `"agentarea-postgresql-secret"` |  |
| global.secrets.redis | string | `"agentarea-redis-secret"` |  |
| global.secrets.rustfs | string | `"agentarea-rustfs-secret"` |  |
| global.secrets.application | string | `"agentarea-app-secrets"` |  |
| global.database.secretName | string | `"agentarea-postgresql-secret"` |  |
| global.database.host | string | `""` |  |
| global.database.port | int | `5432` |  |
| global.database.name | string | `"agentarea"` |  |
| global.database.ssl | bool | `false` |  |
| global.database.sslMode | string | `"disable"` |  |
| global.database.maxConnections | int | `100` |  |
| global.database.connectionTimeout | string | `"30s"` |  |
| global.database.migrations.runAtStartup | bool | `true` |  |
| global.database.migrations.initializationTimeout | string | `"300s"` |  |
| global.redis.host | string | `""` |  |
| global.redis.port | int | `6379` |  |
| global.redis.url | string | `""` |  |
| global.redis.existingSecret | string | `""` |  |
| global.redis.existingSecretKey | string | `"url"` |  |
| global.redis.database | int | `0` |  |
| global.redis.ssl | bool | `false` |  |
| global.redis.maxConnections | int | `50` |  |
| global.redis.connectionTimeout | string | `"5s"` |  |
| global.storage.type | string | `"rustfs"` |  |
| global.storage.endpoint | string | `""` |  |
| global.storage.bucket | string | `"agentarea-documents"` |  |
| global.storage.region | string | `"us-east-1"` |  |
| global.storage.s3.accessKeyId | string | `""` |  |
| global.storage.s3.secretAccessKey | string | `""` |  |
| global.storage.s3.sessionToken | string | `""` |  |
| global.storage.gcs.projectId | string | `""` |  |
| global.storage.gcs.credentials | string | `""` |  |
| global.storage.rustfs.accessKey | string | `""` |  |
| global.storage.rustfs.secretKey | string | `""` |  |
| global.temporal.host | string | `""` |  |
| global.temporal.port | int | `7233` |  |
| global.temporal.namespace | string | `"default"` |  |
| global.temporal.taskQueue | string | `"agent-tasks"` |  |
| global.temporal.client.connectionTimeout | string | `"10s"` |  |
| global.temporal.client.rpcTimeout | string | `"10s"` |  |
| global.temporal.client.longPollTimeout | string | `"60s"` |  |
| global.temporal.worker.maxConcurrentActivityExecutions | int | `10` |  |
| global.temporal.worker.maxConcurrentWorkflowTaskExecutions | int | `5` |  |
| global.temporal.worker.maxConcurrentSessionExecutions | int | `1000` |  |
| global.api.host | string | `"0.0.0.0"` |  |
| global.api.port | int | `8000` |  |
| global.api.publicUrl | string | `""` |  |
| global.api.auth.enabled | bool | `false` |  |
| global.api.auth.headerName | string | `""` |  |
| global.api.auth.headerValue | string | `""` |  |
| global.webapp.url | string | `""` |  |
| global.jobs.kube.namespace | string | `""` |  |
| global.jobs.kube.serviceAccount | string | `""` |  |
| global.jobs.kube.scheduling.spec.nodeSelectors | object | `{}` |  |
| global.jobs.kube.scheduling.check.nodeSelectors | object | `{}` |  |
| global.jobs.kube.scheduling.discover.nodeSelectors | object | `{}` |  |
| global.jobs.kube.resources.limits.cpu | string | `"1000m"` |  |
| global.jobs.kube.resources.limits.memory | string | `"1Gi"` |  |
| global.jobs.kube.resources.requests.cpu | string | `"500m"` |  |
| global.jobs.kube.resources.requests.memory | string | `"512Mi"` |  |
| global.jobs.kube.timeouts.spec | string | `"300s"` |  |
| global.jobs.kube.timeouts.check | string | `"600s"` |  |
| global.jobs.kube.timeouts.discover | string | `"900s"` |  |
| global.jobs.kube.mainContainerImagePullPolicy | string | `"IfNotPresent"` |  |
| global.jobs.kube.sidecarContainerImagePullPolicy | string | `"IfNotPresent"` |  |
| global.jobs.kube.images.socat | string | `"alpine/socat:latest"` |  |
| global.jobs.kube.images.busybox | string | `"busybox:latest"` |  |
| global.jobs.kube.images.curl | string | `"curlimages/curl:latest"` |  |
| global.workloads.resources.mainContainer.cpu.request | string | `"50m"` |  |
| global.workloads.resources.mainContainer.cpu.limit | string | `"1000m"` |  |
| global.workloads.resources.mainContainer.memory.request | string | `"128Mi"` |  |
| global.workloads.resources.mainContainer.memory.limit | string | `"1Gi"` |  |
| global.workloads.resources.sidecarContainer.cpu.request | string | `"10m"` |  |
| global.workloads.resources.sidecarContainer.cpu.limit | string | `"200m"` |  |
| global.workloads.resources.sidecarContainer.memory.request | string | `"64Mi"` |  |
| global.workloads.resources.sidecarContainer.memory.limit | string | `"256Mi"` |  |
| global.serviceMesh.enabled | bool | `false` |  |
| global.serviceMesh.type | string | `"istio"` |  |
| global.monitoring.prometheus.enabled | bool | `true` |  |
| global.monitoring.prometheus.port | int | `9090` |  |
| global.monitoring.prometheus.path | string | `"/metrics"` |  |
| global.monitoring.health.enabled | bool | `true` |  |
| global.monitoring.health.port | int | `8001` |  |
| global.monitoring.health.path | string | `"/health"` |  |
| global.security.podSecurityContext.fsGroup | int | `1000` |  |
| global.security.podSecurityContext.runAsUser | int | `1000` |  |
| global.security.podSecurityContext.runAsNonRoot | bool | `true` |  |
| global.security.containerSecurityContext.allowPrivilegeEscalation | bool | `false` |  |
| global.security.containerSecurityContext.readOnlyRootFilesystem | bool | `true` |  |
| global.security.containerSecurityContext.runAsNonRoot | bool | `true` |  |
| global.security.containerSecurityContext.capabilities.drop[0] | string | `"ALL"` |  |
| global.extraLabels | object | `{}` |  |
| global.extraSelectorLabels | object | `{}` |  |
| ingress.enabled | bool | `false` |  |
| ingress.className | string | `""` |  |
| ingress.annotations | object | `{}` |  |
| ingress.hosts.frontend.host | string | `""` |  |
| ingress.hosts.frontend.paths[0].path | string | `"/"` |  |
| ingress.hosts.frontend.paths[0].pathType | string | `"Prefix"` |  |
| ingress.hosts.backend.host | string | `""` |  |
| ingress.hosts.backend.paths[0].path | string | `"/"` |  |
| ingress.hosts.backend.paths[0].pathType | string | `"Prefix"` |  |
| ingress.hosts.kratos.host | string | `""` |  |
| ingress.hosts.kratos.paths[0].path | string | `"/"` |  |
| ingress.hosts.kratos.paths[0].pathType | string | `"Prefix"` |  |
| ingress.tls | list | `[]` |  |
| backend.enabled | bool | `true` |  |
| backend.replicaCount | int | `1` |  |
| backend.image.repository | string | `"agentarea/agentarea-api"` |  |
| backend.image.tag | string | `"latest"` |  |
| backend.image.pullPolicy | string | `""` |  |
| backend.service.type | string | `"ClusterIP"` |  |
| backend.service.port | int | `8000` |  |
| backend.service.annotations | object | `{}` |  |
| backend.service.labels | object | `{}` |  |
| backend.resources | object | `{}` |  |
| backend.livenessProbe.enabled | bool | `true` |  |
| backend.livenessProbe.initialDelaySeconds | int | `60` |  |
| backend.livenessProbe.periodSeconds | int | `30` |  |
| backend.livenessProbe.timeoutSeconds | int | `10` |  |
| backend.livenessProbe.failureThreshold | int | `3` |  |
| backend.readinessProbe.enabled | bool | `true` |  |
| backend.readinessProbe.initialDelaySeconds | int | `30` |  |
| backend.readinessProbe.periodSeconds | int | `10` |  |
| backend.readinessProbe.timeoutSeconds | int | `5` |  |
| backend.readinessProbe.failureThreshold | int | `3` |  |
| backend.nodeSelector | object | `{}` |  |
| backend.tolerations | list | `[]` |  |
| backend.affinity | object | `{}` |  |
| backend.podAnnotations | object | `{}` |  |
| backend.podLabels | object | `{}` |  |
| backend.extraEnvFrom | list | `[]` |  |
| backend.extraInitContainers | list | `[]` |  |
| backend.podSecurityContext | object | `{}` |  |
| backend.containerSecurityContext | object | `{}` |  |
| backend.extraEnv | list | `[]` |  |
| backend.waitForDependencies | bool | `false` |  |
| frontend.enabled | bool | `true` |  |
| frontend.replicaCount | int | `1` |  |
| frontend.image.repository | string | `"agentarea/agentarea-frontend"` |  |
| frontend.image.tag | string | `"latest"` |  |
| frontend.image.pullPolicy | string | `""` |  |
| frontend.service.type | string | `"ClusterIP"` |  |
| frontend.service.port | int | `3000` |  |
| frontend.service.annotations | object | `{}` |  |
| frontend.service.labels | object | `{}` |  |
| frontend.livenessProbe.enabled | bool | `true` |  |
| frontend.livenessProbe.initialDelaySeconds | int | `30` |  |
| frontend.livenessProbe.periodSeconds | int | `10` |  |
| frontend.livenessProbe.timeoutSeconds | int | `5` |  |
| frontend.livenessProbe.failureThreshold | int | `3` |  |
| frontend.readinessProbe.enabled | bool | `true` |  |
| frontend.readinessProbe.initialDelaySeconds | int | `15` |  |
| frontend.readinessProbe.periodSeconds | int | `5` |  |
| frontend.readinessProbe.timeoutSeconds | int | `3` |  |
| frontend.readinessProbe.failureThreshold | int | `3` |  |
| frontend.resources | object | `{}` |  |
| frontend.podAnnotations | object | `{}` |  |
| frontend.podLabels | object | `{}` |  |
| frontend.nodeSelector | object | `{}` |  |
| frontend.tolerations | list | `[]` |  |
| frontend.affinity | object | `{}` |  |
| frontend.extraEnv | list | `[]` |  |
| frontend.extraVolumes | list | `[]` |  |
| frontend.extraVolumeMounts | list | `[]` |  |
| frontend.extraContainers | list | `[]` |  |
| worker.enabled | bool | `true` |  |
| worker.replicaCount | int | `1` |  |
| worker.image.repository | string | `"agentarea/agentarea-worker"` |  |
| worker.image.tag | string | `"latest"` |  |
| worker.image.pullPolicy | string | `""` |  |
| worker.resources | object | `{}` |  |
| worker.podAnnotations | object | `{}` |  |
| worker.podLabels | object | `{}` |  |
| worker.nodeSelector | object | `{}` |  |
| worker.tolerations | list | `[]` |  |
| worker.affinity | object | `{}` |  |
| worker.extraEnv | list | `[]` |  |
| worker.extraVolumes | list | `[]` |  |
| worker.extraVolumeMounts | list | `[]` |  |
| worker.extraContainers | list | `[]` |  |
| worker.waitForDependencies | bool | `false` |  |
| eventService.enabled | bool | `true` |  |
| eventService.replicaCount | int | `1` |  |
| eventService.image.repository | string | `"agentarea/agentarea-events"` |  |
| eventService.image.tag | string | `"latest"` |  |
| eventService.image.pullPolicy | string | `""` |  |
| eventService.port | int | `8002` |  |
| eventService.pollInterval | string | `"30s"` |  |
| eventService.maxPollers | int | `10` |  |
| eventService.inboundStream | string | `"agentarea.channel.inbound"` |  |
| eventService.telegramPolling.enabled | bool | `false` |  |
| eventService.resources | object | `{}` |  |
| eventService.podAnnotations | object | `{}` |  |
| eventService.podLabels | object | `{}` |  |
| eventService.nodeSelector | object | `{}` |  |
| eventService.tolerations | list | `[]` |  |
| eventService.affinity | object | `{}` |  |
| eventService.livenessProbe.enabled | bool | `true` |  |
| eventService.livenessProbe.initialDelaySeconds | int | `30` |  |
| eventService.livenessProbe.periodSeconds | int | `10` |  |
| eventService.livenessProbe.timeoutSeconds | int | `5` |  |
| eventService.livenessProbe.failureThreshold | int | `3` |  |
| eventService.readinessProbe.enabled | bool | `true` |  |
| eventService.readinessProbe.initialDelaySeconds | int | `10` |  |
| eventService.readinessProbe.periodSeconds | int | `5` |  |
| eventService.readinessProbe.timeoutSeconds | int | `3` |  |
| eventService.readinessProbe.failureThreshold | int | `3` |  |
| eventService.extraEnv | list | `[]` |  |
| mcpManager.enabled | bool | `true` |  |
| mcpManager.replicaCount | int | `1` |  |
| mcpManager.image.repository | string | `"agentarea/agentarea-mcp-manager"` |  |
| mcpManager.image.tag | string | `"latest"` |  |
| mcpManager.service.type | string | `"ClusterIP"` |  |
| mcpManager.service.port | int | `80` |  |
| mcpManager.instanceNetworkPolicy.enabled | bool | `true` |  |
| mcpManager.instanceNetworkPolicy.dnsNamespace | string | `"kube-system"` |  |
| mcpManager.instanceNetworkPolicy.blockedEgressCIDRs[0] | string | `"10.0.0.0/8"` |  |
| mcpManager.instanceNetworkPolicy.blockedEgressCIDRs[1] | string | `"172.16.0.0/12"` |  |
| mcpManager.instanceNetworkPolicy.blockedEgressCIDRs[2] | string | `"192.168.0.0/16"` |  |
| mcpManager.instanceNetworkPolicy.blockedEgressCIDRs[3] | string | `"169.254.0.0/16"` |  |
| mcpManager.instanceNetworkPolicy.extraEgress | list | `[]` |  |
| mcpManager.instancePod.labels | object | `{}` |  |
| mcpManager.instancePod.annotations | object | `{}` |  |
| mcpManager.instancePod.nodeSelector | object | `{}` |  |
| mcpManager.instancePod.tolerations | list | `[]` |  |
| mcpManager.instancePod.affinity | object | `{}` |  |
| mcpManager.instancePod.imagePullSecrets | list | `[]` |  |
| mcpManager.instancePod.priorityClassName | string | `""` |  |
| mcpManager.backend | string | `"kubernetes"` |  |
| mcpManager.domain | string | `"mcp.local"` |  |
| mcpManager.gateway.name | string | `"envoy-gateway"` |  |
| mcpManager.gateway.namespace | string | `"envoy-gateway-system"` |  |
| mcpManager.runtimeClass | string | `""` |  |
| mcpManager.runtime.serviceAccount.create | bool | `true` |  |
| mcpManager.runtime.serviceAccount.name | string | `""` |  |
| mcpManager.runtime.imagePullSecrets | list | `[]` |  |
| mcpManager.securityContext | object | `{}` |  |
| mcpManager.features.enabled[0] | string | `"gateway_api"` |  |
| mcpManager.features.enabled[1] | string | `"state_reconciler"` |  |
| mcpManager.features.variants | object | `{}` |  |
| mcpManager.warmPool.enabled | bool | `false` |  |
| mcpManager.warmPool.image.repository | string | `"agentarea/mcp-runner"` |  |
| mcpManager.warmPool.image.tag | string | `"latest"` |  |
| mcpManager.warmPool.image.pullPolicy | string | `"IfNotPresent"` |  |
| mcpManager.warmPool.maxExecutionTimeoutSeconds | int | `1800` |  |
| mcpManager.warmPool.size | int | `10` |  |
| mcpManager.warmPool.logLevel | string | `"info"` |  |
| mcpManager.warmPool.resources.limits.cpu | string | `"500m"` |  |
| mcpManager.warmPool.resources.limits.memory | string | `"512Mi"` |  |
| mcpManager.warmPool.resources.requests.cpu | string | `"100m"` |  |
| mcpManager.warmPool.resources.requests.memory | string | `"256Mi"` |  |
| mcpManager.resources | object | `{}` |  |
| mcpManager.extraEnv | list | `[]` |  |
| mcpSandboxRunner.enabled | bool | `true` |  |
| mcpSandboxRunner.replicaCount | int | `1` |  |
| mcpSandboxRunner.image.repository | string | `""` |  |
| mcpSandboxRunner.image.tag | string | `""` |  |
| mcpSandboxRunner.consumerGroup | string | `"agentarea-sandbox-runners"` |  |
| mcpSandboxRunner.batchSize | int | `1` |  |
| mcpSandboxRunner.resources.requests.cpu | string | `"50m"` |  |
| mcpSandboxRunner.resources.requests.memory | string | `"96Mi"` |  |
| mcpSandboxRunner.resources.limits.cpu | string | `"500m"` |  |
| mcpSandboxRunner.resources.limits.memory | string | `"512Mi"` |  |
| mcpSandboxRunner.extraEnv | list | `[]` |  |
| temporal.enabled | bool | `true` |  |
| temporal.replicaCount | int | `1` |  |
| temporal.image.repository | string | `"temporalio/auto-setup"` |  |
| temporal.image.tag | string | `"1.29.1"` |  |
| temporal.database.name | string | `"temporal"` |  |
| temporal.database.createJob.enabled | bool | `true` |  |
| temporal.service.type | string | `"ClusterIP"` |  |
| temporal.service.port | int | `7233` |  |
| temporal.resources | object | `{}` |  |
| temporal.extraEnv | list | `[]` |  |
| temporalUi.enabled | bool | `true` |  |
| temporalUi.replicaCount | int | `1` |  |
| temporalUi.image.repository | string | `"temporalio/ui"` |  |
| temporalUi.image.tag | string | `"2.39.0"` |  |
| temporalUi.service.type | string | `"ClusterIP"` |  |
| temporalUi.service.port | int | `8080` |  |
| temporalUi.resources | object | `{}` |  |
| temporalUi.extraEnv | list | `[]` |  |
| postgresql.enabled | bool | `true` |  |
| postgresql.image.repository | string | `"postgres"` |  |
| postgresql.image.tag | string | `"16-alpine"` |  |
| postgresql.resources.limits.cpu | string | `"500m"` |  |
| postgresql.resources.limits.memory | string | `"512Mi"` |  |
| postgresql.resources.requests.cpu | string | `"250m"` |  |
| postgresql.resources.requests.memory | string | `"256Mi"` |  |
| postgresql.persistence.enabled | bool | `true` |  |
| postgresql.persistence.size | string | `"8Gi"` |  |
| postgresql.persistence.storageClass | string | `""` |  |
| redis.enabled | bool | `true` |  |
| valkey.auth.enabled | bool | `true` |  |
| valkey.auth.usersExistingSecret | string | `"agentarea-redis-secret"` |  |
| valkey.auth.aclUsers.default.permissions | string | `"~* &* +@all"` |  |
| valkey.auth.aclUsers.default.passwordKey | string | `"redis-password"` |  |
| valkey.replica.enabled | bool | `false` |  |
| valkey.dataStorage.enabled | bool | `false` |  |
| valkey.dataStorage.requestedSize | string | `"1Gi"` |  |
| valkey.resources.limits.cpu | string | `"250m"` |  |
| valkey.resources.limits.memory | string | `"256Mi"` |  |
| valkey.resources.requests.cpu | string | `"100m"` |  |
| valkey.resources.requests.memory | string | `"128Mi"` |  |
| rustfs.enabled | bool | `true` |  |
| rustfs.image.repository | string | `"rustfs/rustfs"` |  |
| rustfs.image.tag | string | `"latest"` |  |
| rustfs.auth.existingSecret | string | `"agentarea-rustfs-secret"` |  |
| rustfs.defaultBuckets | string | `"agentarea-documents"` |  |
| rustfs.resources.limits.cpu | string | `"500m"` |  |
| rustfs.resources.limits.memory | string | `"512Mi"` |  |
| rustfs.resources.requests.cpu | string | `"250m"` |  |
| rustfs.resources.requests.memory | string | `"256Mi"` |  |
| rustfs.persistence.enabled | bool | `true` |  |
| rustfs.persistence.size | string | `"10Gi"` |  |
| rustfs.readinessProbe.tcpSocket.port | string | `"rustfs"` |  |
| rustfs.readinessProbe.initialDelaySeconds | int | `10` |  |
| rustfs.readinessProbe.periodSeconds | int | `10` |  |
| rustfs.readinessProbe.timeoutSeconds | int | `5` |  |
| rustfs.readinessProbe.failureThreshold | int | `6` |  |
| rustfs.livenessProbe.tcpSocket.port | string | `"rustfs"` |  |
| rustfs.livenessProbe.initialDelaySeconds | int | `20` |  |
| rustfs.livenessProbe.periodSeconds | int | `20` |  |
| rustfs.livenessProbe.timeoutSeconds | int | `5` |  |
| rustfs.livenessProbe.failureThreshold | int | `6` |  |
| jobs.dbMigration.enabled | bool | `true` |  |
| registryReconcile.enabled | bool | `true` |  |
| registryReconcile.registries[0].name | string | `"system-llm-providers"` |  |
| registryReconcile.registries[0].source_url | string | `"https://agentarea-mcp-registry.s3.amazonaws.com/registry/system/llm-providers.json"` |  |
| registryReconcile.registries[1].name | string | `"system-llm-models"` |  |
| registryReconcile.registries[1].source_url | string | `"https://agentarea-mcp-registry.s3.amazonaws.com/registry/system/llm-models.json"` |  |
| registryReconcile.registries[2].name | string | `"system-mcp-servers"` |  |
| registryReconcile.registries[2].source_url | string | `"https://agentarea-mcp-registry.s3.amazonaws.com/registry/system/mcp-servers.json"` |  |
| keto.enabled | bool | `false` |  |
| keto.replicaCount | int | `1` |  |
| keto.image.repository | string | `"oryd/keto"` |  |
| keto.image.tag | string | `"v0.12.0"` |  |
| keto.database.name | string | `"keto"` |  |
| keto.database.createJob.enabled | bool | `true` |  |
| keto.configMapOverrideName | string | `""` |  |
| keto.config | string | `"version: v0.12.0\ndsn: ${DSN}\nnamespaces:\n  location: file:///etc/config/keto/namespaces.keto.ts\nserve:\n  read:\n    host: 0.0.0.0\n    port: 4466\n  write:\n    host: 0.0.0.0\n    port: 4467\n  metrics:\n    host: 0.0.0.0\n    port: 4468\nlog:\n  level: info\n  format: json\n"` |  |
| keto.namespaces | string | `"import { Namespace, Context, SubjectSet } from \"@ory/keto-namespace-types\"\n\nclass User implements Namespace {}\n\nclass Workspace implements Namespace {\n  related: {\n    members: (User | Agent)[]\n  }\n}\n\nclass SkillCollection implements Namespace {\n  related: {\n    parents: Workspace[]\n    viewers: (User | Agent | SubjectSet<Workspace, \"members\">)[]\n    editors: (User | Agent | SubjectSet<Workspace, \"members\">)[]\n    owners: (User | Agent)[]\n  }\n  permits = {\n    use: (ctx: Context): boolean =>\n      this.related.viewers.includes(ctx.subject) ||\n      this.related.editors.includes(ctx.subject) ||\n      this.related.owners.includes(ctx.subject),\n    configure: (ctx: Context): boolean =>\n      this.related.editors.includes(ctx.subject) ||\n      this.related.owners.includes(ctx.subject),\n    manage: (ctx: Context): boolean =>\n      this.related.owners.includes(ctx.subject),\n  }\n}\n\nclass Skill implements Namespace {\n  related: {\n    collections: SkillCollection[]\n    viewers: (User | Agent)[]\n    editors: (User | Agent)[]\n    owners: (User | Agent)[]\n  }\n  permits = {\n    use: (ctx: Context): boolean =>\n      this.related.viewers.includes(ctx.subject) ||\n      this.related.editors.includes(ctx.subject) ||\n      this.related.owners.includes(ctx.subject) ||\n      this.related.collections.traverse((c) => c.permits.use(ctx)),\n    configure: (ctx: Context): boolean =>\n      this.related.editors.includes(ctx.subject) ||\n      this.related.owners.includes(ctx.subject) ||\n      this.related.collections.traverse((c) => c.permits.configure(ctx)),\n    manage: (ctx: Context): boolean =>\n      this.related.owners.includes(ctx.subject) ||\n      this.related.collections.traverse((c) => c.permits.manage(ctx)),\n  }\n}\n\nclass MCPServer implements Namespace {\n  related: {\n    connectors: (User | Agent | SubjectSet<Workspace, \"members\">)[]\n    operators: (User | Agent)[]\n  }\n  permits = {\n    connect: (ctx: Context): boolean =>\n      this.related.connectors.includes(ctx.subject) ||\n      this.related.operators.includes(ctx.subject),\n    manage: (ctx: Context): boolean =>\n      this.related.operators.includes(ctx.subject),\n  }\n}\n\nclass Agent implements Namespace {\n  related: {\n    operators: (User | Agent | SubjectSet<Workspace, \"members\">)[]\n    owners: User[]\n  }\n  permits = {\n    operate: (ctx: Context): boolean =>\n      this.related.operators.includes(ctx.subject) ||\n      this.related.owners.includes(ctx.subject),\n    own: (ctx: Context): boolean => this.related.owners.includes(ctx.subject),\n  }\n}\n"` |  |
| openfga.enabled | bool | `true` |  |
| openfga.replicaCount | int | `1` |  |
| openfga.image.repository | string | `"openfga/openfga"` |  |
| openfga.image.tag | string | `"v1.18.0"` |  |
| openfga.database.name | string | `"openfga"` |  |
| openfga.database.createJob.enabled | bool | `true` |  |
| openfga.log.level | string | `"info"` |  |
| openfga.log.format | string | `"json"` |  |
| openfga.service.httpPort | int | `8080` |  |
| openfga.service.grpcPort | int | `8081` |  |
| openfga.service.metricsPort | int | `2112` |  |
| openfga.service.playgroundPort | int | `3000` |  |
| openfga.playground.enabled | bool | `false` |  |
| openfga.accessControl.storeId | string | `""` |  |
| openfga.accessControl.authorizationModelId | string | `""` |  |
| openfga.accessControl.storeName | string | `"agentarea"` |  |
| openfga.accessControl.autoBootstrap | bool | `true` |  |
| openfga.accessControl.autoApplyModel | bool | `true` |  |
| kratos.enabled | bool | `true` |  |
| kratos.replicaCount | int | `1` |  |
| kratos.image.repository | string | `"oryd/kratos"` |  |
| kratos.image.tag | string | `"v1.3.1"` |  |
| kratos.urls.public | string | `""` |  |
| kratos.urls.publicBrowser | string | `""` |  |
| kratos.urls.admin | string | `""` |  |
| kratos.database.name | string | `"kratos"` |  |
| kratos.database.createJob.enabled | bool | `true` |  |
| kratos.configMapOverrideName | string | `""` |  |
| kratos.files | object | `{}` |  |
| kratos.secretName | string | `""` |  |
| kratos.generateJwks | bool | `true` |  |
| kratos.runtimeSecretName | string | `""` |  |
| kratos.smtp.connection_uri | string | `""` |  |
| kratos.smtp.from_address | string | `"noreply@example.com"` |  |
| kratos.smtp.from_name | string | `"AgentArea"` |  |
| kratos.session.cookieDomain | string | `"localhost"` |  |
| kratos.jwt.kid | string | `"agentarea-jwt-key-1"` |  |
| kratos.jwt.jwks_b64 | string | `""` |  |
| kratos.jwt.jwks_public_b64 | string | `""` |  |
| kratos.jwt.claims_mapper_b64 | string | `""` |  |
| kratos.jwt.issuer | string | `"https://agentarea.dev"` |  |
| kratos.jwt.audience | string | `"agentarea-api"` |  |
| kratos.identitySchema | string | `"{\n  \"$id\": \"https://schemas.ory.sh/presets/kratos/quickstart/email-password/identity.schema.json\",\n  \"$schema\": \"http://json-schema.org/draft-07/schema#\",\n  \"title\": \"Person\",\n  \"type\": \"object\",\n  \"properties\": {\n    \"traits\": {\n      \"type\": \"object\",\n      \"properties\": {\n        \"email\": {\n          \"type\": \"string\",\n          \"format\": \"email\",\n          \"title\": \"Email\",\n          \"ory.sh/kratos\": {\n            \"credentials\": {\n              \"password\": {\n                \"identifier\": true\n              }\n            },\n            \"recovery\": {\n              \"via\": \"email\"\n            }\n          }\n        },\n        \"name\": {\n          \"type\": \"object\",\n          \"properties\": {\n            \"first\": {\n              \"title\": \"First Name\",\n              \"type\": \"string\"\n            },\n            \"last\": {\n              \"title\": \"Last Name\",\n              \"type\": \"string\"\n            }\n          }\n        },\n        \"username\": {\n          \"type\": \"string\",\n          \"title\": \"Username\"\n        }\n      },\n      \"required\": [\n        \"email\"\n      ],\n      \"additionalProperties\": false\n    }\n  }\n}\n"` |  |
| kratos.config.version | string | `"v1.3.1"` |  |
| kratos.config.serve.public.cors.enabled | bool | `true` |  |
| kratos.config.serve.public.cors.allowed_origins[0] | string | `"https://staging-0.agentarea.ai"` |  |
| kratos.config.serve.public.cors.allowed_origins[1] | string | `"https://*.staging-0.agentarea.ai"` |  |
| kratos.config.serve.public.cors.allowed_methods[0] | string | `"POST"` |  |
| kratos.config.serve.public.cors.allowed_methods[1] | string | `"GET"` |  |
| kratos.config.serve.public.cors.allowed_methods[2] | string | `"PUT"` |  |
| kratos.config.serve.public.cors.allowed_methods[3] | string | `"PATCH"` |  |
| kratos.config.serve.public.cors.allowed_methods[4] | string | `"DELETE"` |  |
| kratos.config.serve.public.cors.allowed_headers[0] | string | `"Authorization"` |  |
| kratos.config.serve.public.cors.allowed_headers[1] | string | `"Cookie"` |  |
| kratos.config.serve.public.cors.allowed_headers[2] | string | `"Content-Type"` |  |
| kratos.config.serve.public.cors.allowed_headers[3] | string | `"X-Session-Token"` |  |
| kratos.config.serve.public.cors.exposed_headers[0] | string | `"Content-Type"` |  |
| kratos.config.serve.public.cors.exposed_headers[1] | string | `"Set-Cookie"` |  |
| kratos.config.secrets.cookie[0] | string | `"${KRATOS_SECRETS_COOKIE}"` |  |
| kratos.config.secrets.cipher[0] | string | `"${KRATOS_SECRETS_CIPHER}"` |  |
| kratos.config.ciphers.algorithm | string | `"xchacha20-poly1305"` |  |
| kratos.config.hashers.algorithm | string | `"bcrypt"` |  |
| kratos.config.hashers.bcrypt.cost | int | `8` |  |
| kratos.config.identity.default_schema_id | string | `"default"` |  |
| kratos.config.identity.schemas[0].id | string | `"default"` |  |
| kratos.config.identity.schemas[0].url | string | `"file:///etc/config/kratos/identity.schema.json"` |  |

## Secrets

For production, create required secrets ahead of time and reference them via `global.secrets.*`:

```bash
kubectl create secret generic agentarea-postgresql-secret \
  --from-literal=username=postgres \
  --from-literal=password=<password> \
  --from-literal=postgres-password=<password>

kubectl create secret generic agentarea-redis-secret \
  --from-literal=redis-password=<password>

kubectl create secret generic agentarea-rustfs-secret \
  --from-literal=root-user=<access-key> \
  --from-literal=root-password=<secret-key>
```

## Upgrade

```bash
helm upgrade agentarea agentarea/agentarea -f values.yaml
```
