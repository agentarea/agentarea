{{/*
Expand the name of the chart.
*/}}
{{- define "agentarea.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "agentarea.timeToSeconds" -}}
{{- $v := . -}}
{{- if kindIs "int" $v -}}
{{ $v }}
{{- else if kindIs "string" $v -}}
{{- regexFind "[0-9]+" $v -}}
{{- else -}}
0
{{- end -}}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "agentarea.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "agentarea.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "agentarea.labels" -}}
helm.sh/chart: {{ include "agentarea.chart" . }}
{{ include "agentarea.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "agentarea.selectorLabels" -}}
app.kubernetes.io/name: {{ include "agentarea.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "agentarea.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "agentarea.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Render global image pull secrets for pod specs.
*/}}
{{- define "agentarea.imagePullSecrets" -}}
{{- with .Values.global.image.pullSecrets }}
imagePullSecrets:
{{- toYaml . | nindent 2 }}
{{- end }}
{{- end }}

{{/*
Render MCP runtime image pull secrets for runtime pod service account.
*/}}
{{- define "agentarea.mcpRuntimeImagePullSecrets" -}}
{{- with .Values.mcpManager.runtime.imagePullSecrets }}
imagePullSecrets:
{{- toYaml . | nindent 2 }}
{{- end }}
{{- end }}

{{/*
Create the name of the MCP runtime service account.
*/}}
{{- define "agentarea.mcpRuntimeServiceAccountName" -}}
{{- default (printf "%s-mcp-runtime" (include "agentarea.fullname" .)) .Values.mcpManager.runtime.serviceAccount.name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Frontend URL
*/}}
{{- define "agentarea.frontendUrl" -}}
{{- .Values.global.webapp.url | default (printf "http://%s-frontend:3000" (include "agentarea.fullname" .)) | trimSuffix "/" -}}
{{- end -}}

{{/*
Kratos Public URL
*/}}
{{- define "agentarea.kratosPublicUrl" -}}
{{- .Values.kratos.urls.public | default (printf "http://%s-kratos-public:4433" (include "agentarea.fullname" .)) | trimSuffix "/" -}}
{{- end -}}

{{/*
Kratos Public Browser URL (for client-side JS, falls back to kratosPublicUrl)
*/}}
{{- define "agentarea.kratosPublicBrowserUrl" -}}
{{- .Values.kratos.urls.publicBrowser | default (include "agentarea.kratosPublicUrl" .) | trimSuffix "/" -}}
{{- end -}}

{{/*
Kratos Admin URL
*/}}
{{- define "agentarea.kratosAdminUrl" -}}
{{- .Values.kratos.urls.admin | default (printf "http://%s-kratos-admin:4434" (include "agentarea.fullname" .)) | trimSuffix "/" -}}
{{- end -}}
