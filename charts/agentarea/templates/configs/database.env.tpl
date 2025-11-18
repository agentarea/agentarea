{{- define "agentarea.database.configVars" -}}
POSTGRES_HOST: "{{ .Release.Name }}-postgresql"
POSTGRES_PORT: "{{ .Values.global.database.port }}"
POSTGRES_DB: "{{ .Values.global.database.name }}"
{{- end }}