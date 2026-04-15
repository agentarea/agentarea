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