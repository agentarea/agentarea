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

{{/* Dedicated secret name for worker-to-manager sandbox cleanup authentication. */}}
{{- define "agentarea.sandboxCleanupSecretName" -}}
{{- printf "%s-sandbox-cleanup-auth" (include "agentarea.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Read-only bearer for backend-to-manager sandbox inventory. */}}
{{- define "agentarea.sandboxInspectionSecretName" -}}
{{- printf "%s-sandbox-inspection-auth" (include "agentarea.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Provider-neutral sandbox runtime configuration shared by the HTTP control plane
and the asynchronous runner. Credentials are referenced from Secrets and never
rendered into values-backed ConfigMaps.
*/}}
{{- define "agentarea.sandboxRuntime.envs" -}}
{{- $runtime := .Values.sandboxRuntime -}}
{{- $knownProviders := list "" "kubernetes" "docker" "agentarea" "opensandbox" "e2b" "cube" -}}
{{- if not (has $runtime.provider $knownProviders) -}}
{{- fail (printf "sandboxRuntime.provider=%q is unsupported" $runtime.provider) -}}
{{- end -}}
{{- if and (or (eq $runtime.provider "opensandbox") (eq $runtime.provider "e2b") (eq $runtime.provider "cube")) (not (or $runtime.manifests.allowed $runtime.manifests.locked)) -}}
{{- fail "an external sandboxRuntime.provider requires at least one sandboxRuntime.manifests profile" -}}
{{- end -}}
{{- if $runtime.provider }}
- name: SANDBOX_PROVIDER
  value: {{ $runtime.provider | quote }}
{{- end }}
{{- if $runtime.region }}
- name: SANDBOX_REGION
  value: {{ $runtime.region | quote }}
{{- end }}
- name: SANDBOX_TASK_IDLE_TTL
  value: {{ $runtime.idleTTL | quote }}
- name: SANDBOX_TASK_LEASE_TTL
  value: {{ $runtime.leaseTTL | quote }}
- name: SANDBOX_PROVIDER_SESSION_TTL
  value: {{ $runtime.sessionRecordTTL | quote }}
- name: SANDBOX_PROVIDER_CPU
  value: {{ $runtime.resources.cpu | quote }}
- name: SANDBOX_PROVIDER_MEMORY
  value: {{ $runtime.resources.memory | quote }}
{{- if $runtime.manifests.allowed }}
- name: SANDBOX_RUNTIME_MANIFEST_ALLOWED_JSON
  value: {{ $runtime.manifests.allowed | toJson | quote }}
{{- end }}
{{- if $runtime.manifests.locked }}
- name: SANDBOX_RUNTIME_MANIFEST_LOCKED_JSON
  value: {{ $runtime.manifests.locked | toJson | quote }}
{{- end }}
{{- if eq $runtime.provider "opensandbox" }}
{{- $openSandboxIsolation := required "sandboxRuntime.opensandbox.isolation is required" $runtime.opensandbox.isolation -}}
{{- if and (eq $openSandboxIsolation "container-dev") (not $runtime.opensandbox.allowWeakIsolationForDevelopment) -}}
{{- fail "sandboxRuntime.opensandbox.isolation=container-dev requires allowWeakIsolationForDevelopment=true" -}}
{{- end }}
{{- $egressMode := required "sandboxRuntime.opensandbox.egressMode is required" $runtime.opensandbox.egressMode -}}
{{- if and (eq $openSandboxIsolation "gvisor") (ne $egressMode "host-public") -}}
{{- fail "sandboxRuntime.opensandbox.isolation=gvisor requires egressMode=host-public because OpenSandbox networkPolicy is incompatible with gVisor" -}}
{{- end }}
{{- if and (eq $egressMode "host-public") $runtime.manifests.locked -}}
{{- fail "sandboxRuntime.opensandbox.egressMode=host-public cannot advertise a locked manifest" -}}
{{- end }}
{{- if and $runtime.manifests.allowed (not $runtime.opensandbox.images.allowed) -}}
{{- fail "sandboxRuntime.opensandbox.images.allowed is required for the allowed manifest" -}}
{{- end }}
{{- if and $runtime.manifests.locked (not $runtime.opensandbox.images.locked) -}}
{{- fail "sandboxRuntime.opensandbox.images.locked is required for the locked manifest" -}}
{{- end }}
{{- if and (not $runtime.opensandbox.allowInsecure) (or (not $runtime.opensandbox.apiKeySecretRef.name) (not $runtime.opensandbox.apiKeySecretRef.key)) -}}
{{- fail "sandboxRuntime.opensandbox.apiKeySecretRef name and key are required unless allowInsecure=true" -}}
{{- end }}
{{- if and (not $runtime.opensandbox.secureAccess) (not $runtime.opensandbox.useServerProxy) -}}
{{- fail "sandboxRuntime.opensandbox.secureAccess=false requires useServerProxy=true" -}}
{{- end }}
- name: SANDBOX_OPENSANDBOX_URL
  value: {{ required "sandboxRuntime.opensandbox.url is required" $runtime.opensandbox.url | quote }}
- name: SANDBOX_OPENSANDBOX_ALLOW_INSECURE
  value: {{ $runtime.opensandbox.allowInsecure | quote }}
- name: SANDBOX_OPENSANDBOX_SECURE_ACCESS
  value: {{ $runtime.opensandbox.secureAccess | quote }}
- name: SANDBOX_OPENSANDBOX_ISOLATION
  value: {{ $openSandboxIsolation | quote }}
- name: SANDBOX_OPENSANDBOX_EGRESS_MODE
  value: {{ $egressMode | quote }}
- name: SANDBOX_OPENSANDBOX_PERSIST_WORKSPACE
  value: {{ $runtime.opensandbox.persistWorkspace | quote }}
- name: SANDBOX_OPENSANDBOX_VOLUME_PREFIX
  value: {{ $runtime.opensandbox.volumePrefix | quote }}
- name: SANDBOX_OPENSANDBOX_ALLOW_WEAK_ISOLATION_FOR_DEVELOPMENT
  value: {{ $runtime.opensandbox.allowWeakIsolationForDevelopment | quote }}
- name: SANDBOX_OPENSANDBOX_USE_SERVER_PROXY
  value: {{ $runtime.opensandbox.useServerProxy | quote }}
- name: SANDBOX_OPENSANDBOX_AUTH_HEADER
  value: {{ $runtime.opensandbox.authHeader | quote }}
{{- if $runtime.opensandbox.images.allowed }}
- name: SANDBOX_OPENSANDBOX_IMAGE_ALLOWED
  value: {{ $runtime.opensandbox.images.allowed | quote }}
{{- end }}
{{- if $runtime.opensandbox.images.locked }}
- name: SANDBOX_OPENSANDBOX_IMAGE_LOCKED
  value: {{ $runtime.opensandbox.images.locked | quote }}
{{- end }}
{{- if $runtime.opensandbox.entrypoint }}
- name: SANDBOX_OPENSANDBOX_ENTRYPOINT
  value: {{ $runtime.opensandbox.entrypoint | toJson | quote }}
{{- end }}
{{- with $runtime.opensandbox.apiKeySecretRef }}
{{- if and .name .key }}
- name: SANDBOX_OPENSANDBOX_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .name | quote }}
      key: {{ .key | quote }}
{{- end }}
{{- end }}
{{- end }}
{{- if eq $runtime.provider "e2b" }}
{{- if and $runtime.manifests.allowed (not $runtime.e2b.templates.allowed) -}}
{{- fail "sandboxRuntime.e2b.templates.allowed is required for the allowed manifest" -}}
{{- end }}
{{- if and $runtime.manifests.locked (not $runtime.e2b.templates.locked) -}}
{{- fail "sandboxRuntime.e2b.templates.locked is required for the locked manifest" -}}
{{- end }}
{{- if or (not $runtime.e2b.apiKeySecretRef.name) (not $runtime.e2b.apiKeySecretRef.key) -}}
{{- fail "sandboxRuntime.e2b.apiKeySecretRef name and key are required" -}}
{{- end }}
- name: SANDBOX_E2B_API_URL
  value: {{ required "sandboxRuntime.e2b.apiUrl is required" $runtime.e2b.apiUrl | quote }}
{{- if $runtime.e2b.sandboxUrl }}
- name: SANDBOX_E2B_SANDBOX_URL
  value: {{ $runtime.e2b.sandboxUrl | quote }}
{{- end }}
{{- if $runtime.e2b.internetAccess.locked }}
{{- fail "sandboxRuntime.e2b.internetAccess.locked must remain false" -}}
{{- end }}
- name: SANDBOX_E2B_ALLOW_INTERNET_ALLOWED
  value: {{ $runtime.e2b.internetAccess.allowed | quote }}
- name: SANDBOX_E2B_ALLOW_INTERNET_LOCKED
  value: {{ $runtime.e2b.internetAccess.locked | quote }}
- name: SANDBOX_E2B_ALLOW_INSECURE
  value: {{ $runtime.e2b.allowInsecure | quote }}
{{- if $runtime.e2b.templates.allowed }}
- name: SANDBOX_E2B_TEMPLATE_ALLOWED
  value: {{ $runtime.e2b.templates.allowed | quote }}
{{- end }}
{{- if $runtime.e2b.templates.locked }}
- name: SANDBOX_E2B_TEMPLATE_LOCKED
  value: {{ $runtime.e2b.templates.locked | quote }}
{{- end }}
{{- with $runtime.e2b.apiKeySecretRef }}
{{- if and .name .key }}
- name: SANDBOX_E2B_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .name | quote }}
      key: {{ .key | quote }}
{{- end }}
{{- end }}
{{- end }}
{{- if eq $runtime.provider "cube" }}
{{- if and $runtime.manifests.allowed (not $runtime.cube.templates.allowed) -}}
{{- fail "sandboxRuntime.cube.templates.allowed is required for the allowed manifest" -}}
{{- end }}
{{- if and $runtime.manifests.locked (not $runtime.cube.templates.locked) -}}
{{- fail "sandboxRuntime.cube.templates.locked is required for the locked manifest" -}}
{{- end }}
{{- if or (not $runtime.cube.apiKeySecretRef.name) (not $runtime.cube.apiKeySecretRef.key) -}}
{{- fail "sandboxRuntime.cube.apiKeySecretRef name and key are required" -}}
{{- end }}
- name: SANDBOX_CUBE_API_URL
  value: {{ required "sandboxRuntime.cube.apiUrl is required" $runtime.cube.apiUrl | quote }}
{{- if $runtime.cube.sandboxUrl }}
- name: SANDBOX_CUBE_SANDBOX_URL
  value: {{ $runtime.cube.sandboxUrl | quote }}
{{- end }}
{{- if $runtime.cube.internetAccess.locked }}
{{- fail "sandboxRuntime.cube.internetAccess.locked must remain false" -}}
{{- end }}
- name: SANDBOX_CUBE_ALLOW_INTERNET_ALLOWED
  value: {{ $runtime.cube.internetAccess.allowed | quote }}
- name: SANDBOX_CUBE_ALLOW_INTERNET_LOCKED
  value: {{ $runtime.cube.internetAccess.locked | quote }}
- name: SANDBOX_CUBE_ALLOW_INSECURE
  value: {{ $runtime.cube.allowInsecure | quote }}
{{- if $runtime.cube.templates.allowed }}
- name: SANDBOX_CUBE_TEMPLATE_ALLOWED
  value: {{ $runtime.cube.templates.allowed | quote }}
{{- end }}
{{- if $runtime.cube.templates.locked }}
- name: SANDBOX_CUBE_TEMPLATE_LOCKED
  value: {{ $runtime.cube.templates.locked | quote }}
{{- end }}
{{- with $runtime.cube.apiKeySecretRef }}
{{- if and .name .key }}
- name: SANDBOX_CUBE_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .name | quote }}
      key: {{ .key | quote }}
{{- end }}
{{- end }}
{{- end }}
{{- end -}}

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
