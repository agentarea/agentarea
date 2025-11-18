{{- define "agentarea.temporal.configVars" -}}
WORKFLOW__TEMPORAL_SERVER_URL: "{{ include "agentarea.fullname" . }}-temporal:{{ .Values.global.temporal.port }}"
WORKFLOW__TEMPORAL_NAMESPACE: "{{ .Values.global.temporal.namespace }}"
WORKFLOW__TEMPORAL_TASK_QUEUE: "{{ .Values.global.temporal.taskQueue }}"
{{- end }}