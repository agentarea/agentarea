{{/*
The confinement both kinds of untrusted workload get: MCP servers and agent
sandboxes. Each is called once per workload namespace with a dict:
  root        the chart context
  namespace   the workload namespace
  create      render the Namespace itself
  podSecurity {enforce, warn}
  keep        leave the Namespace behind when the release drops it
*/}}
{{- define "dataplane.workloadNamespace" -}}
{{- if .create }}
apiVersion: v1
kind: Namespace
metadata:
  name: {{ .namespace }}
  {{- if .keep }}
  annotations:
    # Workloads here may carry finalizers only their controller clears; deleting
    # the namespace with the controller in one upgrade would leave it Terminating.
    helm.sh/resource-policy: keep
  {{- end }}
  labels:
    {{- include "dataplane.labels" .root | nindent 4 }}
    pod-security.kubernetes.io/enforce: {{ .podSecurity.enforce }}
    pod-security.kubernetes.io/warn: {{ .podSecurity.warn }}
---
{{- end }}
# Workloads here are third-party code: the namespace's default account keeps no
# API token in their filesystem. They have no business with the Kubernetes API.
apiVersion: v1
kind: ServiceAccount
metadata:
  name: default
  namespace: {{ .namespace }}
automountServiceAccountToken: false
{{- end -}}

{{/*
  root          the chart context
  namespace     the workload namespace
  np            the networkPolicy values
  ingressName   name of the ingress policy
  fromPods      matchLabels of the one pod allowed in, when it is not on the host network
  ingressPorts  ports it may connect to; empty allows all
  egressLabel   pods labelled agentarea.io/egress get DNS and np.egressProxy only
*/}}
{{- define "dataplane.workloadNetworkPolicies" -}}
{{- $np := .np }}
# Nothing reaches a workload except the component that manages it. Pod-to-pod
# stays closed, which is what keeps one tenant's workload from calling another's.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ .ingressName }}
  namespace: {{ .namespace }}
  labels:
    {{- include "dataplane.labels" .root | nindent 4 }}
spec:
  podSelector: {}
  policyTypes: [Ingress]
  ingress:
    - from:
        {{- with .fromPods }}
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: {{ $.root.Release.Namespace }}
          podSelector:
            matchLabels:
              {{- . | nindent 14 }}
        {{- end }}
        {{- range $np.ingressFromCIDRs }}
        - ipBlock:
            cidr: {{ . }}
        {{- end }}
      {{- with .ingressPorts }}
      ports:
        {{- range . }}
        - { protocol: TCP, port: {{ . }} }
        {{- end }}
      {{- end }}
---
# Out: cluster DNS, and the public internet minus denyCIDRs.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: egress-dns-and-public-only
  namespace: {{ .namespace }}
  labels:
    {{- include "dataplane.labels" .root | nindent 4 }}
spec:
  {{- if .egressLabel }}
  podSelector:
    matchExpressions:
      - { key: agentarea.io/egress, operator: DoesNotExist }
  {{- else }}
  podSelector: {}
  {{- end }}
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: {{ $np.dns.namespace }}
          podSelector:
            matchLabels:
              {{- toYaml $np.dns.podLabels | nindent 14 }}
      ports:
        - { protocol: UDP, port: 53 }
        - { protocol: TCP, port: 53 }
    {{- with $np.extraEgress }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
            {{- with $np.denyCIDRs }}
            except:
              {{- toYaml . | nindent 14 }}
            {{- end }}
{{- if .egressLabel }}
---
# Out, for pods labelled agentarea.io/egress: cluster DNS and the egress proxy.
# With no proxy configured they reach DNS only.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: egress-dns-and-proxy-only
  namespace: {{ .namespace }}
  labels:
    {{- include "dataplane.labels" .root | nindent 4 }}
spec:
  podSelector:
    matchExpressions:
      - { key: agentarea.io/egress, operator: Exists }
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: {{ $np.dns.namespace }}
          podSelector:
            matchLabels:
              {{- toYaml $np.dns.podLabels | nindent 14 }}
      ports:
        - { protocol: UDP, port: 53 }
        - { protocol: TCP, port: 53 }
    {{- with $np.egressProxy }}
    {{- $peer := pick . "namespaceSelector" "podSelector" }}
    {{- if or (not $peer) (not .port) }}
    {{- fail "workloads.networkPolicy.egressProxy needs port and namespaceSelector or podSelector" }}
    {{- end }}
    - to:
        - {{ toYaml $peer | nindent 10 | trim }}
      ports:
        - { protocol: TCP, port: {{ .port }} }
    {{- end }}
{{- end }}
{{- end -}}

{{/*
  root          the chart context
  name          policy name
  namespace     the workload namespace
  runtimeClass  the RuntimeClass every pod there must use
*/}}
{{- define "dataplane.requireRuntimeClass" -}}
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: {{ .name }}
  labels:
    {{- include "dataplane.labels" .root | nindent 4 }}
spec:
  failurePolicy: Fail
  matchConstraints:
    namespaceSelector:
      matchLabels:
        kubernetes.io/metadata.name: {{ .namespace }}
    resourceRules:
      - apiGroups: [""]
        apiVersions: [v1]
        operations: [CREATE, UPDATE]
        resources: [pods]
  validations:
    - expression: "has(object.spec.runtimeClassName) && object.spec.runtimeClassName == '{{ .runtimeClass }}'"
      message: "pods in {{ .namespace }} must run with runtimeClassName {{ .runtimeClass }}"
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata:
  name: {{ .name }}
  labels:
    {{- include "dataplane.labels" .root | nindent 4 }}
spec:
  policyName: {{ .name }}
  validationActions: [Deny]
{{- end -}}
