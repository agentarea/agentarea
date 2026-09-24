{{/*
The confinement both kinds of untrusted workload get: MCP servers and agent
sandboxes. Each is called once per workload namespace with a dict:
  root        the chart context
  namespace   the workload namespace
  create      render the Namespace itself
  podSecurity {enforce, warn}
*/}}
{{- define "dataplane.workloadNamespace" -}}
{{- if .create }}
apiVersion: v1
kind: Namespace
metadata:
  name: {{ .namespace }}
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
  podSelector: {}
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
