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
{{- required "global.runtimeCredentials.existingSecret is required" .Values.global.runtimeCredentials.existingSecret -}}
{{- end -}}

{{/* Read-only bearer for backend-to-manager sandbox inventory. */}}
{{- define "agentarea.sandboxInspectionSecretName" -}}
{{- required "global.runtimeCredentials.existingSecret is required" .Values.global.runtimeCredentials.existingSecret -}}
{{- end -}}

{{/* Read/write bearer for internal live-workspace and artifact operations. */}}
{{- define "agentarea.sandboxFileSecretName" -}}
{{- required "global.runtimeCredentials.existingSecret is required" .Values.global.runtimeCredentials.existingSecret -}}
{{- end -}}

{{/* Dedicated bearer for Python-to-manager MCP demand traffic. */}}
{{- define "agentarea.mcpGatewaySecretName" -}}
{{- required "global.runtimeCredentials.existingSecret is required" .Values.global.runtimeCredentials.existingSecret -}}
{{- end -}}

{{- define "agentarea.sandboxCleanupSecretKey" -}}
{{- required "global.runtimeCredentials.keys.sandboxCleanup is required" .Values.global.runtimeCredentials.keys.sandboxCleanup -}}
{{- end -}}
{{- define "agentarea.sandboxInspectionSecretKey" -}}
{{- required "global.runtimeCredentials.keys.sandboxInspection is required" .Values.global.runtimeCredentials.keys.sandboxInspection -}}
{{- end -}}
{{- define "agentarea.sandboxFileSecretKey" -}}
{{- required "global.runtimeCredentials.keys.sandboxFile is required" .Values.global.runtimeCredentials.keys.sandboxFile -}}
{{- end -}}
{{- define "agentarea.mcpGatewaySecretKey" -}}
{{- required "global.runtimeCredentials.keys.mcpGateway is required" .Values.global.runtimeCredentials.keys.mcpGateway -}}
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
{{- if not (hasKey $runtime "allowInternet") -}}
{{- fail "sandboxRuntime.allowInternet is required; sandbox egress has no implicit default" -}}
{{- end -}}
{{- if and (or (eq $runtime.provider "opensandbox") (eq $runtime.provider "e2b") (eq $runtime.provider "cube")) (empty $runtime.manifest) -}}
{{- fail "an external sandboxRuntime.provider requires sandboxRuntime.manifest" -}}
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
- name: SANDBOX_PROVIDER_PROVISIONING_TIMEOUT
  value: {{ required "sandboxRuntime.provisioningTimeout is required; ambiguous creates must have a bounded reconciliation window" $runtime.provisioningTimeout | quote }}
- name: SANDBOX_PROVIDER_SESSION_TTL
  value: {{ $runtime.sessionRecordTTL | quote }}
- name: SANDBOX_EXECUTION_RECORD_TTL
  value: {{ required "sandboxRuntime.executionRecordTTL is required; execution-record retention has no application default" $runtime.executionRecordTTL | quote }}
- name: SANDBOX_MAX_EXECUTION_TIMEOUT_SECONDS
  value: {{ required "sandboxRuntime.maxExecutionTimeoutSeconds is required; execution admission has no application default" $runtime.maxExecutionTimeoutSeconds | quote }}
- name: SANDBOX_DEFAULT_EXECUTION_TIMEOUT_SECONDS
  value: {{ required "sandboxRuntime.defaultExecutionTimeoutSeconds is required; execution admission has no application default" $runtime.defaultExecutionTimeoutSeconds | quote }}
- name: SANDBOX_EXECUTION_QUEUE_TIMEOUT
  value: {{ required "sandboxRuntime.executionQueueTimeout is required; queued work needs a server-owned expiry" $runtime.executionQueueTimeout | quote }}
- name: SANDBOX_EXECUTION_COMPLETION_GRACE
  value: {{ required "sandboxRuntime.executionCompletionGrace is required; post-command completion needs a bounded deadline" $runtime.executionCompletionGrace | quote }}
- name: SANDBOX_PROVIDER_CPU
  value: {{ $runtime.resources.cpu | quote }}
- name: SANDBOX_PROVIDER_MEMORY
  value: {{ $runtime.resources.memory | quote }}
- name: SANDBOX_ALLOW_INTERNET
  value: {{ $runtime.allowInternet | quote }}
{{- if not (empty $runtime.manifest) }}
- name: SANDBOX_RUNTIME_MANIFEST_JSON
  value: {{ $runtime.manifest | toJson | quote }}
{{- end }}
{{- if eq $runtime.provider "opensandbox" }}
{{- $openSandboxIsolation := required "sandboxRuntime.opensandbox.isolation is required" $runtime.opensandbox.isolation -}}
{{- if not (has $openSandboxIsolation (list "gvisor" "container-dev")) -}}
{{- fail "sandboxRuntime.opensandbox.isolation currently supports only gvisor or container-dev; kata/firecracker require verifiable provider attestation" -}}
{{- end -}}
{{- $openSandboxRuntimeIdentity := "" -}}
{{- if eq $openSandboxIsolation "gvisor" -}}
{{- $openSandboxRuntimeIdentity = required "sandboxRuntime.opensandbox.runtimeIdentity is required for gvisor" $runtime.opensandbox.runtimeIdentity -}}
{{- end -}}
{{- if and (eq $openSandboxIsolation "container-dev") (not $runtime.opensandbox.allowWeakIsolationForDevelopment) -}}
{{- fail "sandboxRuntime.opensandbox.isolation=container-dev requires allowWeakIsolationForDevelopment=true" -}}
{{- end }}
{{- $egressMode := required "sandboxRuntime.opensandbox.egressMode is required" $runtime.opensandbox.egressMode -}}
{{- if and (eq $openSandboxIsolation "gvisor") (ne $egressMode "host-public") -}}
{{- fail "sandboxRuntime.opensandbox.isolation=gvisor requires egressMode=host-public because OpenSandbox networkPolicy is incompatible with gVisor" -}}
{{- end }}
{{- if and (eq $openSandboxIsolation "container-dev") (ne $egressMode "provider") -}}
{{- fail "sandboxRuntime.opensandbox.isolation=container-dev requires egressMode=provider" -}}
{{- end }}
{{- if and (eq $egressMode "host-public") (not $runtime.allowInternet) -}}
{{- fail "sandboxRuntime.opensandbox.egressMode=host-public requires sandboxRuntime.allowInternet=true; use provider mode for deny-by-default policy" -}}
{{- end }}
{{- if not $runtime.opensandbox.image -}}
{{- fail "sandboxRuntime.opensandbox.image is required" -}}
{{- end }}
{{- if and (eq $openSandboxIsolation "gvisor") (not (contains "@sha256:" $runtime.opensandbox.image)) -}}
{{- fail "sandboxRuntime.opensandbox.image must use an immutable sha256 digest for gvisor" -}}
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
{{- if $openSandboxRuntimeIdentity }}
- name: SANDBOX_OPENSANDBOX_RUNTIME_IDENTITY
  value: {{ $openSandboxRuntimeIdentity | quote }}
{{- end }}
- name: SANDBOX_OPENSANDBOX_EGRESS_MODE
  value: {{ $egressMode | quote }}
- name: SANDBOX_OPENSANDBOX_ALLOW_WEAK_ISOLATION_FOR_DEVELOPMENT
  value: {{ $runtime.opensandbox.allowWeakIsolationForDevelopment | quote }}
- name: SANDBOX_OPENSANDBOX_USE_SERVER_PROXY
  value: {{ $runtime.opensandbox.useServerProxy | quote }}
- name: SANDBOX_OPENSANDBOX_AUTH_HEADER
  value: {{ $runtime.opensandbox.authHeader | quote }}
- name: SANDBOX_OPENSANDBOX_IMAGE
  value: {{ $runtime.opensandbox.image | quote }}
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
{{- if not $runtime.e2b.template -}}
{{- fail "sandboxRuntime.e2b.template is required" -}}
{{- end }}
{{- if or (not $runtime.e2b.apiKeySecretRef.name) (not $runtime.e2b.apiKeySecretRef.key) -}}
{{- fail "sandboxRuntime.e2b.apiKeySecretRef name and key are required" -}}
{{- end }}
- name: SANDBOX_E2B_API_URL
  value: {{ required "sandboxRuntime.e2b.apiUrl is required" $runtime.e2b.apiUrl | quote }}
- name: SANDBOX_E2B_ISOLATION
  value: {{ required "sandboxRuntime.e2b.isolation is required; an E2B-compatible endpoint must attest a verifiable boundary" $runtime.e2b.isolation | quote }}
- name: SANDBOX_E2B_ATTESTATION_PATH
  value: {{ required "sandboxRuntime.e2b.attestationPath is required" $runtime.e2b.attestationPath | quote }}
{{- if $runtime.e2b.runtimeIdentity }}
- name: SANDBOX_E2B_RUNTIME_IDENTITY
  value: {{ $runtime.e2b.runtimeIdentity | quote }}
{{- end }}
{{- if $runtime.e2b.sandboxUrl }}
- name: SANDBOX_E2B_SANDBOX_URL
  value: {{ $runtime.e2b.sandboxUrl | quote }}
{{- end }}
- name: SANDBOX_E2B_ALLOW_INSECURE
  value: {{ $runtime.e2b.allowInsecure | quote }}
- name: SANDBOX_E2B_TEMPLATE
  value: {{ $runtime.e2b.template | quote }}
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
{{- if not $runtime.cube.template -}}
{{- fail "sandboxRuntime.cube.template is required" -}}
{{- end }}
{{- if or (not $runtime.cube.apiKeySecretRef.name) (not $runtime.cube.apiKeySecretRef.key) -}}
{{- fail "sandboxRuntime.cube.apiKeySecretRef name and key are required" -}}
{{- end }}
- name: SANDBOX_CUBE_API_URL
  value: {{ required "sandboxRuntime.cube.apiUrl is required" $runtime.cube.apiUrl | quote }}
- name: SANDBOX_CUBE_ISOLATION
  value: {{ required "sandboxRuntime.cube.isolation is required; a Cube endpoint must attest a verifiable boundary" $runtime.cube.isolation | quote }}
- name: SANDBOX_CUBE_ATTESTATION_PATH
  value: {{ required "sandboxRuntime.cube.attestationPath is required" $runtime.cube.attestationPath | quote }}
{{- if $runtime.cube.runtimeIdentity }}
- name: SANDBOX_CUBE_RUNTIME_IDENTITY
  value: {{ $runtime.cube.runtimeIdentity | quote }}
{{- end }}
{{- if $runtime.cube.sandboxUrl }}
- name: SANDBOX_CUBE_SANDBOX_URL
  value: {{ $runtime.cube.sandboxUrl | quote }}
{{- end }}
- name: SANDBOX_CUBE_ALLOW_INSECURE
  value: {{ $runtime.cube.allowInsecure | quote }}
- name: SANDBOX_CUBE_TEMPLATE
  value: {{ $runtime.cube.template | quote }}
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
Which backend the manager drives.

"dataplane" hands MCP containers to a remote host running the same binary in
data-plane mode; "kubernetes" creates them in a cluster. Derived from whether a
data plane was named rather than configured separately, so the two cannot
disagree about where workloads go.

Half-configuration is refused. A URL without a token reaches a data plane that
must reject it, and a token without a URL names no data plane at all; either one
would otherwise render as in-cluster mode and put untrusted MCP servers on the
control plane's own nodes while the operator believes they were moved off.
*/}}
{{- define "agentarea.mcpManager.backendType" -}}
{{- $dp := .Values.mcpManager.dataPlane | default dict -}}
{{- $url := $dp.url | default "" -}}
{{- $secret := $dp.tokenSecret | default "" -}}
{{- $key := $dp.tokenKey | default "" -}}
{{- if and $url (or (not $secret) (not $key)) -}}
{{- fail "mcpManager.dataPlane.url is set but tokenSecret/tokenKey are not: name the Secret and key holding the shared data-plane token" -}}
{{- end -}}
{{- if and (or $secret $key) (not $url) -}}
{{- fail "mcpManager.dataPlane token is configured but url is empty: name the data plane to reach, or clear the token to run MCP containers in this cluster" -}}
{{- end -}}
{{- if $url -}}dataplane{{- else -}}kubernetes{{- end -}}
{{- end -}}

{{/*
Directory the execution cluster kubeconfig is projected into. One definition
feeds both the volume mount and the path handed to the manager, so the two
cannot drift; it matches the path the dev compose stack uses.
*/}}
{{- define "agentarea.mcpManager.executionKubeconfigDir" -}}
/etc/agentarea/exec
{{- end -}}

{{/*
Path of the execution cluster kubeconfig inside the mcp-manager pod, or empty
when no execution cluster is configured — the manager reads empty as "use the
cluster I am in".

Half-configuration is refused rather than rendered. A key without a Secret, or
a Secret without a key, would otherwise render as in-cluster mode: untrusted
MCP servers and agent sandboxes landing on the control plane's nodes while the
operator believes they were moved off, with nothing in the output to say so.
*/}}
{{- define "agentarea.mcpManager.executionKubeconfigPath" -}}
{{- $exec := .Values.mcpManager.executionCluster | default dict -}}
{{- $secret := $exec.kubeconfigSecret | default "" -}}
{{- $key := $exec.kubeconfigKey | default "" -}}
{{- if and $secret (not $key) -}}
{{- fail "mcpManager.executionCluster.kubeconfigSecret is set but kubeconfigKey is empty: name the key inside that Secret that holds the kubeconfig" -}}
{{- end -}}
{{- if and $key (not $secret) -}}
{{- fail "mcpManager.executionCluster.kubeconfigKey is set but kubeconfigSecret is empty: name the existing Secret holding the execution cluster kubeconfig, or clear kubeconfigKey to run workloads in this cluster" -}}
{{- end -}}
{{- if $secret -}}
{{- printf "%s/%s" (include "agentarea.mcpManager.executionKubeconfigDir" .) $key -}}
{{- end -}}
{{- end -}}

{{/*
Mount and volume for the execution cluster kubeconfig; both render empty when
no execution cluster is configured.

Every workload that builds a Kubernetes backend from the mcpManager env block
needs these, and that is not only the manager: the sandbox runner builds the
same backend from the same KUBERNETES_KUBECONFIG and exits if the file it names
is absent. Keeping the pair here is what stops one deployment from getting the
path without the file.
*/}}
{{- define "agentarea.mcpManager.executionKubeconfigMount" }}
{{- if include "agentarea.mcpManager.executionKubeconfigPath" . }}
# Credentials for the separate execution cluster, at the path handed to the
# process as KUBERNETES_KUBECONFIG.
- name: execution-kubeconfig
  mountPath: {{ include "agentarea.mcpManager.executionKubeconfigDir" . }}
  readOnly: true
{{- end }}
{{- end }}

{{- define "agentarea.mcpManager.executionKubeconfigVolume" }}
{{- if include "agentarea.mcpManager.executionKubeconfigPath" . }}
- name: execution-kubeconfig
  secret:
    secretName: {{ .Values.mcpManager.executionCluster.kubeconfigSecret | quote }}
    # Project only the configured key, so an unrelated entry in the same Secret
    # never becomes a file in this pod.
    items:
      - key: {{ .Values.mcpManager.executionCluster.kubeconfigKey | quote }}
        path: {{ .Values.mcpManager.executionCluster.kubeconfigKey | quote }}
{{- end }}
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
