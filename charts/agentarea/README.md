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
- PV provisioner for PostgreSQL/MinIO persistence (if enabled)

## Installing with external services

If you have existing PostgreSQL, Redis or S3-compatible storage, disable bundled dependencies and set endpoints:

```yaml
postgresql:
  enabled: false
redis:
  enabled: false
minio:
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
| backend.affinity | object | `{}` |  |
| backend.containerSecurityContext | object | `{}` |  |
| backend.enabled | bool | `true` |  |
| backend.extraEnv | list | `[]` |  |
| backend.extraEnvFrom | list | `[]` |  |
| backend.extraInitContainers | list | `[]` |  |
| backend.image.pullPolicy | string | `""` |  |
| backend.image.repository | string | `"agentarea/agentarea-api"` |  |
| backend.image.tag | string | `"latest"` |  |
| backend.livenessProbe.enabled | bool | `true` |  |
| backend.livenessProbe.failureThreshold | int | `3` |  |
| backend.livenessProbe.initialDelaySeconds | int | `60` |  |
| backend.livenessProbe.periodSeconds | int | `30` |  |
| backend.livenessProbe.timeoutSeconds | int | `10` |  |
| backend.nodeSelector | object | `{}` |  |
| backend.podAnnotations | object | `{}` |  |
| backend.podLabels | object | `{}` |  |
| backend.podSecurityContext | object | `{}` |  |
| backend.readinessProbe.enabled | bool | `true` |  |
| backend.readinessProbe.failureThreshold | int | `3` |  |
| backend.readinessProbe.initialDelaySeconds | int | `30` |  |
| backend.readinessProbe.periodSeconds | int | `10` |  |
| backend.readinessProbe.timeoutSeconds | int | `5` |  |
| backend.replicaCount | int | `1` |  |
| backend.resources | object | `{}` |  |
| backend.service.annotations | object | `{}` |  |
| backend.service.labels | object | `{}` |  |
| backend.service.port | int | `8000` |  |
| backend.service.type | string | `"ClusterIP"` |  |
| backend.tolerations | list | `[]` |  |
| backend.waitForDependencies | bool | `false` |  |
| frontend.affinity | object | `{}` |  |
| frontend.enabled | bool | `true` |  |
| frontend.extraContainers | list | `[]` |  |
| frontend.extraEnv | list | `[]` |  |
| frontend.extraVolumeMounts | list | `[]` |  |
| frontend.extraVolumes | list | `[]` |  |
| frontend.image.pullPolicy | string | `""` |  |
| frontend.image.repository | string | `"agentarea/agentarea-frontend"` |  |
| frontend.image.tag | string | `"latest"` |  |
| frontend.livenessProbe.enabled | bool | `true` |  |
| frontend.livenessProbe.failureThreshold | int | `3` |  |
| frontend.livenessProbe.initialDelaySeconds | int | `30` |  |
| frontend.livenessProbe.periodSeconds | int | `10` |  |
| frontend.livenessProbe.timeoutSeconds | int | `5` |  |
| frontend.nodeSelector | object | `{}` |  |
| frontend.podAnnotations | object | `{}` |  |
| frontend.podLabels | object | `{}` |  |
| frontend.readinessProbe.enabled | bool | `true` |  |
| frontend.readinessProbe.failureThreshold | int | `3` |  |
| frontend.readinessProbe.initialDelaySeconds | int | `15` |  |
| frontend.readinessProbe.periodSeconds | int | `5` |  |
| frontend.readinessProbe.timeoutSeconds | int | `3` |  |
| frontend.replicaCount | int | `1` |  |
| frontend.resources | object | `{}` |  |
| frontend.service.annotations | object | `{}` |  |
| frontend.service.labels | object | `{}` |  |
| frontend.service.port | int | `3000` |  |
| frontend.service.type | string | `"ClusterIP"` |  |
| frontend.tolerations | list | `[]` |  |
| fullnameOverride | string | `""` |  |
| global.api.auth.enabled | bool | `false` |  |
| global.api.auth.headerName | string | `""` |  |
| global.api.auth.headerValue | string | `""` |  |
| global.api.host | string | `"0.0.0.0"` |  |
| global.api.port | int | `8000` |  |
| global.api.rateLimit.enabled | bool | `true` |  |
| global.api.rateLimit.requestsPerMinute | int | `1000` |  |
| global.cluster.name | string | `"agentarea"` |  |
| global.cluster.type | string | `"kubernetes"` |  |
| global.database.connectionTimeout | string | `"30s"` |  |
| global.database.host | string | `""` |  |
| global.database.maxConnections | int | `100` |  |
| global.database.migrations.initializationTimeout | string | `"300s"` |  |
| global.database.migrations.runAtStartup | bool | `true` |  |
| global.database.name | string | `"agentarea"` |  |
| global.database.port | int | `5432` |  |
| global.database.secretName | string | `"agentarea-postgresql-secret"` |  |
| global.database.ssl | bool | `false` |  |
| global.database.sslMode | string | `"prefer"` |  |
| global.deploymentEnv | string | `"production"` |  |
| global.edition | string | `"community"` |  |
| global.extraLabels | object | `{}` |  |
| global.extraSelectorLabels | object | `{}` |  |
| global.image.pullPolicy | string | `"IfNotPresent"` |  |
| global.image.pullSecrets | list | `[]` |  |
| global.image.registry | string | `""` |  |
| global.jobs.kube.images.busybox | string | `"busybox:latest"` |  |
| global.jobs.kube.images.curl | string | `"curlimages/curl:latest"` |  |
| global.jobs.kube.images.socat | string | `"alpine/socat:latest"` |  |
| global.jobs.kube.mainContainerImagePullPolicy | string | `"IfNotPresent"` |  |
| global.jobs.kube.namespace | string | `""` |  |
| global.jobs.kube.resources.limits.cpu | string | `"1000m"` |  |
| global.jobs.kube.resources.limits.memory | string | `"1Gi"` |  |
| global.jobs.kube.resources.requests.cpu | string | `"500m"` |  |
| global.jobs.kube.resources.requests.memory | string | `"512Mi"` |  |
| global.jobs.kube.scheduling.check.nodeSelectors | object | `{}` |  |
| global.jobs.kube.scheduling.discover.nodeSelectors | object | `{}` |  |
| global.jobs.kube.scheduling.spec.nodeSelectors | object | `{}` |  |
| global.jobs.kube.serviceAccount | string | `""` |  |
| global.jobs.kube.sidecarContainerImagePullPolicy | string | `"IfNotPresent"` |  |
| global.jobs.kube.timeouts.check | string | `"600s"` |  |
| global.jobs.kube.timeouts.discover | string | `"900s"` |  |
| global.jobs.kube.timeouts.spec | string | `"300s"` |  |
| global.monitoring.health.enabled | bool | `true` |  |
| global.monitoring.health.path | string | `"/health"` |  |
| global.monitoring.health.port | int | `8001` |  |
| global.monitoring.prometheus.enabled | bool | `true` |  |
| global.monitoring.prometheus.path | string | `"/metrics"` |  |
| global.monitoring.prometheus.port | int | `9090` |  |
| global.redis.connectionTimeout | string | `"5s"` |  |
| global.redis.database | int | `0` |  |
| global.redis.host | string | `""` |  |
| global.redis.maxConnections | int | `50` |  |
| global.redis.port | int | `6379` |  |
| global.redis.ssl | bool | `false` |  |
| global.secrets.application | string | `"agentarea-app-secrets"` |  |
| global.secrets.minio | string | `"agentarea-minio-secret"` |  |
| global.secrets.postgresql | string | `"agentarea-postgresql-secret"` |  |
| global.secrets.redis | string | `"agentarea-redis-secret"` |  |
| global.security.containerSecurityContext.allowPrivilegeEscalation | bool | `false` |  |
| global.security.containerSecurityContext.capabilities.drop[0] | string | `"ALL"` |  |
| global.security.containerSecurityContext.readOnlyRootFilesystem | bool | `true` |  |
| global.security.containerSecurityContext.runAsNonRoot | bool | `true` |  |
| global.security.podSecurityContext.fsGroup | int | `1000` |  |
| global.security.podSecurityContext.runAsNonRoot | bool | `true` |  |
| global.security.podSecurityContext.runAsUser | int | `1000` |  |
| global.serviceAccountName | string | `"agentarea"` |  |
| global.serviceMesh.enabled | bool | `false` |  |
| global.serviceMesh.type | string | `"istio"` |  |
| global.storage.bucket | string | `"agentarea-documents"` |  |
| global.storage.endpoint | string | `""` |  |
| global.storage.gcs.credentials | string | `""` |  |
| global.storage.gcs.projectId | string | `""` |  |
| global.storage.minio.accessKey | string | `""` |  |
| global.storage.minio.secretKey | string | `""` |  |
| global.storage.region | string | `"us-east-1"` |  |
| global.storage.s3.accessKeyId | string | `""` |  |
| global.storage.s3.secretAccessKey | string | `""` |  |
| global.storage.s3.sessionToken | string | `""` |  |
| global.storage.type | string | `"minio"` |  |
| global.temporal.client.connectionTimeout | string | `"10s"` |  |
| global.temporal.client.longPollTimeout | string | `"60s"` |  |
| global.temporal.client.rpcTimeout | string | `"10s"` |  |
| global.temporal.host | string | `""` |  |
| global.temporal.namespace | string | `"default"` |  |
| global.temporal.port | int | `7233` |  |
| global.temporal.taskQueue | string | `"agent-tasks"` |  |
| global.temporal.worker.maxConcurrentActivityExecutions | int | `10` |  |
| global.temporal.worker.maxConcurrentSessionExecutions | int | `1000` |  |
| global.temporal.worker.maxConcurrentWorkflowTaskExecutions | int | `5` |  |
| global.version | string | `"0.0.1"` |  |
| global.webapp.url | string | `""` |  |
| global.workloads.resources.mainContainer.cpu.limit | string | `"1000m"` |  |
| global.workloads.resources.mainContainer.cpu.request | string | `"50m"` |  |
| global.workloads.resources.mainContainer.memory.limit | string | `"1Gi"` |  |
| global.workloads.resources.mainContainer.memory.request | string | `"128Mi"` |  |
| global.workloads.resources.sidecarContainer.cpu.limit | string | `"200m"` |  |
| global.workloads.resources.sidecarContainer.cpu.request | string | `"10m"` |  |
| global.workloads.resources.sidecarContainer.memory.limit | string | `"256Mi"` |  |
| global.workloads.resources.sidecarContainer.memory.request | string | `"64Mi"` |  |
| ingress.annotations | object | `{}` |  |
| ingress.className | string | `""` |  |
| ingress.enabled | bool | `false` |  |
| ingress.hosts.backend.host | string | `""` |  |
| ingress.hosts.backend.paths[0].path | string | `"/"` |  |
| ingress.hosts.backend.paths[0].pathType | string | `"Prefix"` |  |
| ingress.hosts.frontend.host | string | `""` |  |
| ingress.hosts.frontend.paths[0].path | string | `"/"` |  |
| ingress.hosts.frontend.paths[0].pathType | string | `"Prefix"` |  |
| ingress.hosts.kratos.host | string | `""` |  |
| ingress.hosts.kratos.paths[0].path | string | `"/"` |  |
| ingress.hosts.kratos.paths[0].pathType | string | `"Prefix"` |  |
| ingress.tls | list | `[]` |  |
| jobs.bootstrap.enabled | bool | `false` |  |
| jobs.bootstrap.image.repository | string | `"agentarea/agentarea-bootstrap"` |  |
| jobs.bootstrap.image.tag | string | `"latest"` |  |
| jobs.dbMigration.enabled | bool | `true` |  |
| kratos.config.ciphers.algorithm | string | `"xchacha20-poly1305"` |  |
| kratos.config.dsn | string | `"${DSN}"` |  |
| kratos.config.hashers.algorithm | string | `"bcrypt"` |  |
| kratos.config.hashers.bcrypt.cost | int | `8` |  |
| kratos.config.identity.default_schema_id | string | `"default"` |  |
| kratos.config.identity.schemas[0].id | string | `"default"` |  |
| kratos.config.identity.schemas[0].url | string | `"file:///etc/config/kratos/identity.schema.json"` |  |
| kratos.config.secrets.cipher[0] | string | `"SECRET-KEY-FOR-DEV-32-CHARACTERS"` |  |
| kratos.config.secrets.cookie[0] | string | `"PLEASE-CHANGE-ME-I-AM-VERY-INSECURE-dev-only"` |  |
| kratos.config.serve.public.cors.allowed_headers[0] | string | `"Authorization"` |  |
| kratos.config.serve.public.cors.allowed_headers[1] | string | `"Cookie"` |  |
| kratos.config.serve.public.cors.allowed_headers[2] | string | `"Content-Type"` |  |
| kratos.config.serve.public.cors.allowed_headers[3] | string | `"X-Session-Token"` |  |
| kratos.config.serve.public.cors.allowed_methods[0] | string | `"POST"` |  |
| kratos.config.serve.public.cors.allowed_methods[1] | string | `"GET"` |  |
| kratos.config.serve.public.cors.allowed_methods[2] | string | `"PUT"` |  |
| kratos.config.serve.public.cors.allowed_methods[3] | string | `"PATCH"` |  |
| kratos.config.serve.public.cors.allowed_methods[4] | string | `"DELETE"` |  |
| kratos.config.serve.public.cors.allowed_origins[0] | string | `"https://staging-0.agentarea.ai"` |  |
| kratos.config.serve.public.cors.allowed_origins[1] | string | `"https://*.staging-0.agentarea.ai"` |  |
| kratos.config.serve.public.cors.enabled | bool | `true` |  |
| kratos.config.serve.public.cors.exposed_headers[0] | string | `"Content-Type"` |  |
| kratos.config.serve.public.cors.exposed_headers[1] | string | `"Set-Cookie"` |  |
| kratos.config.version | string | `"v1.3.1"` |  |
| kratos.configMapOverrideName | string | `""` |  |
| kratos.database.name | string | `"kratos"` |  |
| kratos.enabled | bool | `true` |  |
| kratos.files | object | `{}` |  |
| kratos.generateJwks | bool | `false` |  |
| kratos.identitySchema | string | `"{\n  \"$id\": \"https://schemas.ory.sh/presets/kratos/quickstart/email-password/identity.schema.json\",\n  \"$schema\": \"http://json-schema.org/draft-07/schema#\",\n  \"title\": \"Person\",\n  \"type\": \"object\",\n  \"properties\": {\n    \"traits\": {\n      \"type\": \"object\",\n      \"properties\": {\n        \"email\": {\n          \"type\": \"string\",\n          \"format\": \"email\",\n          \"title\": \"Email\",\n          \"ory.sh/kratos\": {\n            \"credentials\": {\n              \"password\": {\n                \"identifier\": true\n              }\n            },\n            \"recovery\": {\n              \"via\": \"email\"\n            }\n          }\n        },\n        \"name\": {\n          \"type\": \"object\",\n          \"properties\": {\n            \"first\": {\n              \"title\": \"First Name\",\n              \"type\": \"string\"\n            },\n            \"last\": {\n              \"title\": \"Last Name\",\n              \"type\": \"string\"\n            }\n          }\n        },\n        \"username\": {\n          \"type\": \"string\",\n          \"title\": \"Username\"\n        }\n      },\n      \"required\": [\n        \"email\"\n      ],\n      \"additionalProperties\": false\n    }\n  }\n}\n"` |  |
| kratos.image.repository | string | `"oryd/kratos"` |  |
| kratos.image.tag | string | `"v1.3.1"` |  |
| kratos.jwt.audience | string | `"agentarea-api"` |  |
| kratos.jwt.claims_mapper_b64 | string | `"bG9jYWwgY2xhaW1zID0gc3RkLmV4dFZhcignY2xhaW1zJyk7CmxvY2FsIHNlc3Npb24gPSBzdGQuZXh0VmFyKCdzZXNzaW9uJyk7Cgp7CiAgY2xhaW1zOiB7CiAgICAvLyBTdGFuZGFyZCBKV1QgY2xhaW1zIC0gaW5oZXJpdCBmcm9tIGRlZmF1bHQgY2xhaW1zCiAgICBpc3M6ICdodHRwczovL2FnZW50YXJlYS5kZXYnLAogICAgc3ViOiBzZXNzaW9uLmlkZW50aXR5LmlkLAogICAgYXVkOiAnYWdlbnRhcmVhLWFwaScsCiAgICBleHA6IGNsYWltcy5leHAsCiAgICBpYXQ6IGNsYWltcy5pYXQsCgogICAgLy8gQ3VzdG9tIGNsYWltcwogICAgZW1haWw6IGlmIHN0ZC5vYmplY3RIYXMoc2Vzc2lvbi5pZGVudGl0eS50cmFpdHMsICdlbWFpbCcpIHRoZW4gc2Vzc2lvbi5pZGVudGl0eS50cmFpdHMuZW1haWwgZWxzZSBudWxsLAogICAgdXNlcm5hbWU6IGlmIHN0ZC5vYmplY3RIYXMoc2Vzc2lvbi5pZGVudGl0eS50cmFpdHMsICd1c2VybmFtZScpIHRoZW4gc2Vzc2lvbi5pZGVudGl5LnRyYWl0cy51c2VybmFtZSBlbHNlIG51bGwsCiAgICBuYW1lOiBpZiBzdGQub2JqZWN0SGFzKHNlc3Npb24uaWRlbnRpdHkudHJhaXRzLCAnbmFtZScpIHRoZW4gewogICAgICBmaXJzdDogaWYgc3RkLm9iamVjdEhhcyhzZXNzaW9uLmlkZW50aXR5LnRyYWl0cy5uYW1lLCAnZmlyc3QnKSB0aGVuIHNlc3Npb24uaWRlbnRpdHkudHJhaXRzLm5hbWUuZmlyc3QgZWxzZSBudWxsLAogICAgICBsYXN0OiBpZiBzdGQub2JqZWN0SGFzKHNlc3Npb24uaWRlbnRpdHkudHJhaXRzLm5hbWUsICdsYXN0JykgdGhlbiBzZXNzaW9uLmlkZW50aXR5LnRyYWl0cy5uYW1lLmxhc3QgZWxzZSBudWxsLAogICAgfSBlbHNlIG51bGwsCgogICAgLy8gS3JhdG9zIHNwZWNpZmljIGNsYWltcwogICAgc2NoZW1hX2lkOiBzZXNzaW9uLmlkZW50aXR5LnNjaGVtYV9pZCwKICAgIGFhbDogc2Vzc2lvbi5hdXRoZW50aWNhdG9yX2Fzc3VyYW5jZV9sZXZlbCwKICAgIHNlc3Npb25faWQ6IHNlc3Npb24uaWQsCiAgfQp9Cg=="` |  |
| kratos.jwt.issuer | string | `"https://agentarea.dev"` |  |
| kratos.jwt.jwks_b64 | string | `"ewogICJrZXlzIjogWwogICAgewogICAgICAia3R5IjogIkVDIiwKICAgICAgImtpZCI6ICJhZ2VudGFyZWEtand0LWtleS0xIiwKICAgICAgInVzZSI6ICJzaWciLAogICAgICAiYWxnIjogIkVTMjU2IiwKICAgICAgImNydiI6ICJQLTI1NiIsCiAgICAgICJ4IjogIk1LQkNUTkljS1VTRGlpMTF5U3MzNTI2aURaOEFpVG83VHU2S1BBcXY3RDQiLAogICAgICAieSI6ICI0RXRsNlNSVzJZaUxVck41dmZ2Vkh1aHA3eDhQeGx0bVdXbGJiTTRJRnlNIiwKICAgICAgImQiOiAiODcwTUI2Z2Z1VEo0SHRVblV2WU15SnByNWVVWk5QNEJrNDNiVmRqM2VBRSIKICAgIH0KICBdCn0="` |  |
| kratos.jwt.kid | string | `"agentarea-jwt-key-1"` |  |
| kratos.replicaCount | int | `1` |  |
| kratos.secretName | string | `""` |  |
| kratos.session.cookieDomain | string | `"localhost"` |  |
| kratos.smtp.connection_uri | string | `""` |  |
| kratos.smtp.from_address | string | `"noreply@example.com"` |  |
| kratos.smtp.from_name | string | `"AgentArea"` |  |
| kratos.urls.admin | string | `""` |  |
| kratos.urls.public | string | `""` |  |
| mcpManager.enabled | bool | `true` |  |
| mcpManager.extraEnv | list | `[]` |  |
| mcpManager.image.repository | string | `"agentarea/agentarea-mcp-manager"` |  |
| mcpManager.image.tag | string | `"latest"` |  |
| mcpManager.replicaCount | int | `1` |  |
| mcpManager.resources | object | `{}` |  |
| mcpManager.securityContext.capabilities.add[0] | string | `"SYS_ADMIN"` |  |
| mcpManager.securityContext.privileged | bool | `true` |  |
| mcpManager.service.port | int | `80` |  |
| mcpManager.service.type | string | `"ClusterIP"` |  |
| minio.auth.existingSecret | string | `"agentarea-minio-secret"` |  |
| minio.defaultBuckets | string | `"agentarea-documents"` |  |
| minio.enabled | bool | `true` |  |
| minio.image.repository | string | `"minio/minio"` |  |
| minio.image.tag | string | `"latest"` |  |
| minio.persistence.enabled | bool | `true` |  |
| minio.persistence.size | string | `"10Gi"` |  |
| minio.resources.limits.cpu | string | `"500m"` |  |
| minio.resources.limits.memory | string | `"512Mi"` |  |
| minio.resources.requests.cpu | string | `"250m"` |  |
| minio.resources.requests.memory | string | `"256Mi"` |  |
| nameOverride | string | `""` |  |
| postgresql.auth.database | string | `"agentarea"` |  |
| postgresql.auth.existingSecret | string | `"agentarea-postgresql-secret"` |  |
| postgresql.auth.secretKeys.adminPasswordKey | string | `"postgres-password"` |  |
| postgresql.auth.secretKeys.userPasswordKey | string | `"password"` |  |
| postgresql.auth.username | string | `"postgres"` |  |
| postgresql.enabled | bool | `true` |  |
| postgresql.primary.persistence.enabled | bool | `true` |  |
| postgresql.primary.persistence.size | string | `"8Gi"` |  |
| postgresql.primary.resources.limits.cpu | string | `"500m"` |  |
| postgresql.primary.resources.limits.memory | string | `"512Mi"` |  |
| postgresql.primary.resources.requests.cpu | string | `"250m"` |  |
| postgresql.primary.resources.requests.memory | string | `"256Mi"` |  |
| redis.auth.enabled | bool | `true` |  |
| redis.auth.existingSecret | string | `"agentarea-redis-secret"` |  |
| redis.auth.existingSecretPasswordKey | string | `"redis-password"` |  |
| redis.enabled | bool | `true` |  |
| redis.master.persistence.enabled | bool | `false` |  |
| redis.master.resources.limits.cpu | string | `"250m"` |  |
| redis.master.resources.limits.memory | string | `"256Mi"` |  |
| redis.master.resources.requests.cpu | string | `"100m"` |  |
| redis.master.resources.requests.memory | string | `"128Mi"` |  |
| serviceAccount.annotations | object | `{}` |  |
| serviceAccount.create | bool | `true` |  |
| serviceAccount.name | string | `"agentarea"` |  |
| temporal.database.name | string | `"temporal"` |  |
| temporal.enabled | bool | `true` |  |
| temporal.extraEnv | list | `[]` |  |
| temporal.image.repository | string | `"temporalio/auto-setup"` |  |
| temporal.image.tag | string | `"1.29.1"` |  |
| temporal.replicaCount | int | `1` |  |
| temporal.resources | object | `{}` |  |
| temporal.service.port | int | `7233` |  |
| temporal.service.type | string | `"ClusterIP"` |  |
| temporalUi.enabled | bool | `true` |  |
| temporalUi.extraEnv | list | `[]` |  |
| temporalUi.image.repository | string | `"temporalio/ui"` |  |
| temporalUi.image.tag | string | `"2.39.0"` |  |
| temporalUi.replicaCount | int | `1` |  |
| temporalUi.resources | object | `{}` |  |
| temporalUi.service.port | int | `8080` |  |
| temporalUi.service.type | string | `"ClusterIP"` |  |
| worker.affinity | object | `{}` |  |
| worker.enabled | bool | `true` |  |
| worker.extraContainers | list | `[]` |  |
| worker.extraEnv | list | `[]` |  |
| worker.extraVolumeMounts | list | `[]` |  |
| worker.extraVolumes | list | `[]` |  |
| worker.image.pullPolicy | string | `""` |  |
| worker.image.repository | string | `"agentarea/agentarea-worker"` |  |
| worker.image.tag | string | `"latest"` |  |
| worker.nodeSelector | object | `{}` |  |
| worker.podAnnotations | object | `{}` |  |
| worker.podLabels | object | `{}` |  |
| worker.replicaCount | int | `1` |  |
| worker.resources | object | `{}` |  |
| worker.tolerations | list | `[]` |  |
| worker.waitForDependencies | bool | `false` |  |

## Secrets

For production, create required secrets ahead of time and reference them via `global.secrets.*`:

```bash
kubectl create secret generic agentarea-postgresql-secret \
  --from-literal=username=postgres \
  --from-literal=password=<password> \
  --from-literal=postgres-password=<password>

kubectl create secret generic agentarea-redis-secret \
  --from-literal=redis-password=<password>

kubectl create secret generic agentarea-minio-secret \
  --from-literal=root-user=<access-key> \
  --from-literal=root-password=<secret-key>
```

## Upgrade

```bash
helm upgrade agentarea agentarea/agentarea -f values.yaml
```
