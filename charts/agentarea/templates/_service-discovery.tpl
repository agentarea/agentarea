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
RustFS host helper
*/}}
{{- define "agentarea.rustfs.host" -}}
{{- if .Values.global.storage.endpoint -}}
{{ .Values.global.storage.endpoint }}
{{- else -}}
{{ .Release.Name }}-rustfs
{{- end -}}
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
the externally reachable API URL (API_BASE_URL).
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