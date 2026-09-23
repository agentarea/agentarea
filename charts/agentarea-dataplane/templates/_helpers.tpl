{{- define "dataplane.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "dataplane.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{- define "dataplane.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "dataplane.tokenSecretName" -}}
{{- .Values.dataPlane.auth.existingSecret | default (printf "%s-token" (include "dataplane.fullname" .)) -}}
{{- end -}}

{{- define "dataplane.tokenSecretKey" -}}
{{- if .Values.dataPlane.auth.existingSecret -}}{{ .Values.dataPlane.auth.existingSecretKey }}{{- else -}}token{{- end -}}
{{- end -}}

{{/*
Refuse a configuration that would render something unsafe or unusable, naming
the value to fix. Called from the Deployment so every render passes through it.
*/}}
{{- define "dataplane.validate" -}}
{{- if not .Values.dataPlane.id -}}
{{- fail "dataPlane.id is empty: every data plane needs its own id, stamped on the instances it owns" -}}
{{- end -}}
{{- if and (not .Values.dataPlane.auth.existingSecret) (not .Values.dataPlane.auth.token) -}}
{{- fail "dataPlane.auth: set existingSecret (or token, for development); a data plane without a token hands container creation to anyone who reaches it" -}}
{{- end -}}
{{- if and (not .Values.dataPlane.auth.existingSecret) (lt (len .Values.dataPlane.auth.token) 32) -}}
{{- fail "dataPlane.auth.token must be at least 32 characters; the data plane refuses to start with a shorter one" -}}
{{- end -}}
{{- if not .Values.workloads.runtimeClassName -}}
{{- fail "workloads.runtimeClassName is empty: MCP servers are untrusted code and must run under a sandboxing RuntimeClass" -}}
{{- end -}}
{{- if and .Values.exposure.hostNetwork.enabled (not .Values.exposure.hostNetwork.bindAddress) -}}
{{- fail "exposure.hostNetwork.bindAddress is empty: on the host network the API must bind one address, not every interface the node has" -}}
{{- end -}}
{{- end -}}
