{{- define "agentarea.redis.configVars" -}}
REDIS_HOST: "{{ .Release.Name }}-redis-master"
REDIS_PORT: "{{ .Values.global.redis.port }}"
{{- end }}