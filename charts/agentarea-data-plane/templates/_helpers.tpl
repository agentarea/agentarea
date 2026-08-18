{{- define "agentarea-data-plane.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "agentarea-data-plane.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := include "agentarea-data-plane.name" . }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "agentarea-data-plane.labels" -}}
app.kubernetes.io/name: {{ include "agentarea-data-plane.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | quote }}
{{- end }}

{{- define "agentarea-data-plane.selectorLabels" -}}
app.kubernetes.io/name: {{ include "agentarea-data-plane.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "agentarea-data-plane.serviceAccountName" -}}
{{- default (include "agentarea-data-plane.fullname" .) .Values.serviceAccount.name }}
{{- end }}

{{- define "agentarea-data-plane.identityClaimName" -}}
{{- default (include "agentarea-data-plane.fullname" .) .Values.identity.existingClaim }}
{{- end }}

{{- define "agentarea-data-plane.image" -}}
{{- if .Values.image.digest -}}
{{- printf "%s@%s" .Values.image.repository .Values.image.digest }}
{{- else -}}
{{- printf "%s:%s" .Values.image.repository .Values.image.tag }}
{{- end -}}
{{- end }}
