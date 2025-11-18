{{- define "agentarea.temporalServer.configVars" -}}
DB: "postgres12"
DB_PORT: "5432"
POSTGRES_SEEDS: "{{ .Release.Name }}-postgresql"
DBNAME: "{{ .Values.global.database.name }}"
BIND_ON_IP: "0.0.0.0"
{{- end }}