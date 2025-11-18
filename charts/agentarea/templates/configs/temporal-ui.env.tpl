{{- define "agentarea.temporalUi.configVars" -}}
TEMPORAL_ADDRESS: "{{ include "agentarea.fullname" . }}-temporal:7233"
TEMPORAL_CORS_ORIGINS: "http://localhost:3000"
{{- end }}