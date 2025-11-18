{{- define "agentarea.mcpManagerOnly.configVars" -}}
LOG_LEVEL: "INFO"
CORE_API_URL: "http://{{ include "agentarea.fullname" . }}-backend:8000"
MCP_PROXY_HOST: "http://localhost:80"
TRAEFIK_NETWORK: "podman"
{{- end }}