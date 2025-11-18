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
{{ .Release.Name }}-postgresql
{{- end -}}
{{- end -}}

{{/*
Redis host helper
*/}}
{{- define "agentarea.redis.host" -}}
{{- if .Values.global.redis.host -}}
{{ .Values.global.redis.host }}
{{- else -}}
{{ .Release.Name }}-redis-master
{{- end -}}
{{- end -}}

{{/*
MinIO host helper
*/}}
{{- define "agentarea.minio.host" -}}
{{- if .Values.global.storage.endpoint -}}
{{ .Values.global.storage.endpoint }}
{{- else -}}
{{ .Release.Name }}-minio
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