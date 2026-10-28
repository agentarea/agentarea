{{/*
Service discovery helper templates
*/}}

{{/*
Database host helper
*/}}
{{- define "agentarea.database.host" -}}
{{- if .Values.global.database.host -}}
{{ .Values.global.database.host }}
{{- else -}}
{{ include "agentarea.fullname" . }}-postgresql
{{- end -}}
{{- end -}}

{{/*
Valkey (Redis-compatible) host helper
*/}}
{{- define "agentarea.redis.host" -}}
{{- if .Values.global.redis.host -}}
{{ .Values.global.redis.host }}
{{- else -}}
{{ .Release.Name }}-valkey
{{- end -}}
{{- end -}}

{{/*
Object store: the bundled RustFS, or the external store named by
global.storage.endpoint and global.storage.existingSecret. Never both.
*/}}
{{- define "agentarea.storage.endpoint" -}}
{{- if .Values.rustfs.enabled -}}
{{- if or .Values.global.storage.endpoint .Values.global.storage.existingSecret -}}
{{- fail "global.storage.endpoint and global.storage.existingSecret name an external object store; set rustfs.enabled=false to use it" -}}
{{- end -}}
http://{{ .Release.Name }}-rustfs:9000
{{- else -}}
{{- required "global.storage.endpoint is required when rustfs.enabled=false" .Values.global.storage.endpoint -}}
{{- end -}}
{{- end -}}

{{- define "agentarea.storage.credentialsSecret" -}}
{{- if .Values.rustfs.enabled -}}
{{ .Values.global.secrets.rustfs }}
{{- else -}}
{{- required "global.storage.existingSecret is required when rustfs.enabled=false" .Values.global.storage.existingSecret -}}
{{- end -}}
{{- end -}}

{{- define "agentarea.storage.accessKeyKey" -}}
{{- if .Values.rustfs.enabled -}}root-user{{- else -}}{{ .Values.global.storage.accessKeyKey }}{{- end -}}
{{- end -}}

{{- define "agentarea.storage.secretKeyKey" -}}
{{- if .Values.rustfs.enabled -}}root-password{{- else -}}{{ .Values.global.storage.secretKeyKey }}{{- end -}}
{{- end -}}

{{/*
Temporal host helper
*/}}
{{- define "agentarea.temporal.host" -}}
{{- if .Values.global.temporal.host -}}
{{ .Values.global.temporal.host }}
{{- else -}}
{{ include "agentarea.fullname" . }}-temporal
{{- end -}}
{{- end -}}

{{/*
Backend service URL helper
*/}}
{{- define "agentarea.backend.url" -}}
http://{{ include "agentarea.fullname" . }}-backend:{{ .Values.backend.service.port }}
{{- end -}}

{{/*
Backend public API URL helper.
Resolution order:
  1. .Values.global.api.publicUrl (explicit override, e.g. https://api.example.com)
  2. https://{{ ingress.hosts.backend.host }} when ingress is enabled and host is set
  3. Internal ClusterIP service URL (agentarea.backend.url)
Used for OAuth protected-resource metadata and any env var that must advertise
the externally reachable API URL (AGENTAREA_API_URL).
*/}}
{{- define "agentarea.backend.apiUrl" -}}
{{- if .Values.global.api.publicUrl -}}
{{ .Values.global.api.publicUrl }}
{{- else if and .Values.ingress.enabled .Values.ingress.hosts.backend.host -}}
https://{{ .Values.ingress.hosts.backend.host }}
{{- else -}}
{{ include "agentarea.backend.url" . }}
{{- end -}}
{{- end -}}

{{/*
Frontend service URL helper
*/}}
{{- define "agentarea.frontend.url" -}}
http://{{ include "agentarea.fullname" . }}-frontend:{{ .Values.frontend.service.port }}
{{- end -}}

{{/*
MCP Manager service URL helper
*/}}
{{- define "agentarea.mcpManager.url" -}}
http://{{ include "agentarea.fullname" . }}-mcp-manager:{{ .Values.mcpManager.service.port }}
{{- end -}}