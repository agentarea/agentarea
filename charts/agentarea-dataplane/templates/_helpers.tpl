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
The sandbox server is named apart from the data plane: sharing the data plane's
selector labels would put it behind the data plane's Service and inside the MCP
servers' ingress policy.
*/}}
{{- define "dataplane.sandboxServerName" -}}
{{- printf "%s-sandbox-server" (include "dataplane.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "dataplane.sandboxServerSelectorLabels" -}}
app.kubernetes.io/name: agentarea-sandbox-server
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "dataplane.sandboxServerLabels" -}}
{{ include "dataplane.sandboxServerSelectorLabels" . }}
app.kubernetes.io/version: {{ .Values.sandboxes.server.image.tag | splitList "@" | first | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{- define "dataplane.sandboxApiKeySecretName" -}}
{{- .Values.sandboxes.server.auth.existingSecret | default (printf "%s-api-key" (include "dataplane.sandboxServerName" .)) -}}
{{- end -}}

{{- define "dataplane.sandboxApiKeySecretKey" -}}
{{- if .Values.sandboxes.server.auth.existingSecret -}}{{ .Values.sandboxes.server.auth.existingSecretKey }}{{- else -}}api-key{{- end -}}
{{- end -}}

{{- define "dataplane.validateSandboxes" -}}
{{- $s := .Values.sandboxes -}}
{{- if and (not $s.server.auth.existingSecret) (not $s.server.auth.apiKey) -}}
{{- fail "sandboxes.server.auth: set existingSecret (or apiKey, for development); the sandbox server would otherwise create pods for anyone who reaches it" -}}
{{- end -}}
{{- if and (not $s.server.auth.existingSecret) (lt (len $s.server.auth.apiKey) 32) -}}
{{- fail "sandboxes.server.auth.apiKey must be at least 32 characters" -}}
{{- end -}}
{{- if not $s.runtimeClassName -}}
{{- fail "sandboxes.runtimeClassName is empty: sandboxes run agent-written code and must run under a sandboxing RuntimeClass" -}}
{{- end -}}
{{- if not (has $s.secureRuntimeType (list "gvisor" "kata" "firecracker")) -}}
{{- fail "sandboxes.secureRuntimeType must be gvisor, kata or firecracker" -}}
{{- end -}}
{{- if and .Values.exposure.hostNetwork.enabled (eq (int $s.server.port) (int .Values.dataPlane.port)) -}}
{{- fail "sandboxes.server.port equals dataPlane.port: on the host network both bind the same address" -}}
{{- end -}}
{{- if and .Values.exposure.hostNetwork.enabled $s.networkPolicy.enabled (not $s.networkPolicy.ingressFromCIDRs) -}}
{{- fail "sandboxes.networkPolicy.ingressFromCIDRs is empty with exposure.hostNetwork: an ingress rule with no source admits every source; list the node address and the pod bridge gateway" -}}
{{- end -}}
{{- if has $s.namespace (list .Release.Namespace .Values.workloads.namespace "kube-system" "kube-public" "default") -}}
{{- fail (printf "sandboxes.namespace %q is shared with other workloads: sandbox confinement and the server's Role would apply to them" $s.namespace) -}}
{{- end -}}
{{- $controller := index .Values "opensandbox-controller" -}}
{{- if and $controller.enabled (ne $controller.namespaceOverride .Release.Namespace) -}}
{{- fail (printf "opensandbox-controller.namespaceOverride is %q but the release namespace is %q: the controller would land in a namespace nothing creates" $controller.namespaceOverride .Release.Namespace) -}}
{{- end -}}
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
{{- if has .Values.workloads.namespace (list .Release.Namespace "kube-system" "kube-public" "default") -}}
{{- fail (printf "workloads.namespace %q is shared with other workloads: MCP server confinement and the data plane's Role would apply to them" .Values.workloads.namespace) -}}
{{- end -}}
{{- if and .Values.exposure.hostNetwork.enabled (not .Values.exposure.hostNetwork.bindAddress) -}}
{{- fail "exposure.hostNetwork.bindAddress is empty: on the host network the API must bind one address, not every interface the node has" -}}
{{- end -}}
{{- if and .Values.exposure.hostNetwork.enabled .Values.workloads.networkPolicy.enabled (not .Values.workloads.networkPolicy.ingressFromCIDRs) -}}
{{- fail "workloads.networkPolicy.ingressFromCIDRs is empty with exposure.hostNetwork: an ingress rule with no source admits every source; list the node address and the pod bridge gateway" -}}
{{- end -}}
{{- end -}}

{{/* OpenSandbox server configuration: the Kubernetes runtime, one namespace. */}}
{{- define "dataplane.sandboxServerConfig" -}}
{{- $s := .Values.sandboxes -}}
[server]
host = {{ ternary .Values.exposure.hostNetwork.bindAddress "0.0.0.0" .Values.exposure.hostNetwork.enabled | quote }}
port = {{ $s.server.port | int }}
max_sandbox_timeout_seconds = {{ $s.server.maxSandboxTimeoutSeconds | int }}
timeout_keep_alive = 30
timeout_graceful_shutdown = 15

[log]
level = {{ $s.server.logLevel | quote }}
file_enabled = false

[runtime]
type = "kubernetes"
execd_image = {{ $s.server.execdImage | quote }}

[kubernetes]
namespace = {{ $s.namespace | quote }}
workload_provider = "batchsandbox"
batchsandbox_template_file = "/etc/opensandbox/batchsandbox-template.yaml"
image_pull_policy = "IfNotPresent"
informer_enabled = true
sandbox_create_timeout_seconds = {{ $s.server.createTimeoutSeconds | int }}

[secure_runtime]
type = {{ $s.secureRuntimeType | quote }}
k8s_runtime_class = {{ $s.runtimeClassName | quote }}

[storage]
allowed_host_paths = []

[store]
type = "sqlite"
path = "/var/lib/opensandbox/opensandbox.db"

[ingress]
mode = "direct"

[renew_intent]
enabled = false
{{- end -}}
