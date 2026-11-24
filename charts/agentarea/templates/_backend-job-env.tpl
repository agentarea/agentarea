{{/*
The backend's own environment for a job that runs the API image against the
authorization graph: the graph settings, then backend/global env vars, secrets
and extra env, with the model never applied from a job.
*/}}
{{- define "agentarea.backendJobEnv" -}}
{{- /* The model is the API's to apply, so this is set once, last, and
       dropped from every other source. */}}
{{- $forced := list "AGENTAREA_AUTHZ_FGA_APPLY_MODEL" }}
{{- if .Values.openfga.enabled }}
# The authorization graph, as the backend reaches it.
- name: AGENTAREA_AUTHZ_BACKEND
  value: "openfga"
- name: AGENTAREA_AUTHZ_FGA_URL
  value: "http://{{ include "agentarea.fullname" . }}-openfga:{{ .Values.openfga.service.httpPort | default 8080 }}"
- name: AGENTAREA_AUTHZ_FGA_STORE_ID
  value: {{ .Values.openfga.accessControl.storeId | quote }}
- name: AGENTAREA_AUTHZ_FGA_MODEL_ID
  value: {{ .Values.openfga.accessControl.authorizationModelId | quote }}
- name: AGENTAREA_AUTHZ_FGA_BOOTSTRAP
  value: {{ .Values.openfga.accessControl.autoBootstrap | quote }}
- name: AGENTAREA_AUTHZ_FGA_STORE_NAME
  value: {{ .Values.openfga.accessControl.storeName | default "agentarea" | quote }}
{{- end }}
{{- if or .Values.backend.envVars .Values.global.envVars }}
{{- $backendEnv := deepCopy (default dict .Values.backend.envVars) -}}
{{- $globalEnv := default dict .Values.global.envVars -}}
{{- range $k, $v := mergeOverwrite $backendEnv $globalEnv }}
{{- if not (has $k $forced) }}
- name: {{ $k }}
  value: {{ $v | quote }}
{{- end }}
{{- end }}
{{- end }}
{{- if .Values.backend.secrets }}
{{- $secretName := ( .Values.backend.secretsName | default (printf "%s-backend-secrets" .Release.Name) ) }}
{{- range $k, $v := .Values.backend.secrets }}
{{- if not (has $k $forced) }}
- name: {{ $k }}
  valueFrom:
    secretKeyRef:
      name: {{ $secretName }}
      key: {{ $k }}
{{- end }}
{{- end }}
{{- end }}
{{- $extraEnv := list }}
{{- range .Values.backend.extraEnv }}
{{- if not (has .name $forced) }}
{{- $extraEnv = append $extraEnv . }}
{{- end }}
{{- end }}
{{- if $extraEnv }}
{{- toYaml $extraEnv | nindent 12 }}
{{- end }}
- name: AGENTAREA_AUTHZ_FGA_APPLY_MODEL
  value: "false"
{{- end }}
