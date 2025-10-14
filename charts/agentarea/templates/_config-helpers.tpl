{{/*
Configuration helper templates for environment variables
Following Airbyte's modular approach to config management
*/}}

{{/*
Database configuration variables
*/}}
{{- define "agentarea.database.configVars" -}}
POSTGRES_HOST: "{{ .Release.Name }}-postgresql"
POSTGRES_PORT: "{{ .Values.global.database.port }}"
POSTGRES_DB: "{{ .Values.global.database.database }}"
{{- end }}

{{/*
Redis configuration variables
*/}}
{{- define "agentarea.redis.configVars" -}}
REDIS_HOST: "{{ .Release.Name }}-redis-master"
REDIS_PORT: "{{ .Values.global.redis.port }}"
{{- end }}

{{/*
Storage (S3/MinIO) configuration variables
*/}}
{{- define "agentarea.storage.configVars" -}}
AWS_REGION: "{{ .Values.global.storage.region }}"
S3_BUCKET_NAME: "{{ .Values.global.storage.bucket }}"
AWS_ENDPOINT_URL: "http://{{ .Release.Name }}-minio:9000"
{{- end }}

{{/*
Temporal configuration variables
*/}}
{{- define "agentarea.temporal.configVars" -}}
WORKFLOW__TEMPORAL_SERVER_URL: "{{ include "agentarea.fullname" . }}-temporal:{{ .Values.global.temporal.port }}"
WORKFLOW__TEMPORAL_NAMESPACE: "{{ .Values.global.temporal.namespace }}"
WORKFLOW__TEMPORAL_TASK_QUEUE: "{{ .Values.global.temporal.taskQueue }}"
{{- end }}

{{/*
MCP Manager configuration variables
*/}}
{{- define "agentarea.mcpManager.configVars" -}}
MCP_MANAGER_URL: "http://{{ include "agentarea.fullname" . }}-mcp-manager/api/mcp"
MCP_PROXY_HOST: "http://{{ include "agentarea.fullname" . }}-mcp-manager"
MCP_CLIENT_TIMEOUT: "30"
{{- end }}

{{/*
Backend-specific configuration variables
*/}}
{{- define "agentarea.backend.configVars" -}}
PORT: "8000"
LOG_LEVEL: "info"
{{- end }}

{{/*
Worker-specific configuration variables
*/}}
{{- define "agentarea.worker.configVars" -}}
WORKFLOW__USE_WORKFLOW_EXECUTION: "true"
WORKFLOW__WORKFLOW_ENGINE: "temporal"
WORKFLOW__TEMPORAL_MAX_CONCURRENT_ACTIVITIES: "10"
WORKFLOW__TEMPORAL_MAX_CONCURRENT_WORKFLOWS: "5"
TASK__ENABLE_DYNAMIC_ACTIVITY_DISCOVERY: "true"
DEBUG: "false"
ENVIRONMENT: "production"
{{- end }}

{{/*
Frontend-specific configuration variables
*/}}
{{- define "agentarea.frontend.configVars" -}}
PORT: "3000"
NODE_ENV: "production"
NEXT_PUBLIC_API_URL: "http://{{ include "agentarea.fullname" . }}-backend:8000"
KRATOS_PUBLIC_URL: "http://ory-kratos-public:80"
KRATOS_ADMIN_URL: "http://ory-kratos-admin:80"
HYDRA_PUBLIC_URL: "http://ory-hydra-public:4444"
HYDRA_ADMIN_URL: "http://ory-hydra-admin:4445"
{{- end }}

{{/*
MCP Manager specific configuration variables
*/}}
{{- define "agentarea.mcpManagerOnly.configVars" -}}
LOG_LEVEL: "INFO"
CORE_API_URL: "http://{{ include "agentarea.fullname" . }}-backend:8000"
MCP_PROXY_HOST: "http://localhost:80"
{{- end }}
