{{- define "agentarea.mcpManager.configVars" -}}
MCP_MANAGER_URL: "http://{{ include "agentarea.fullname" . }}-mcp-manager/api/mcp"
MCP_PROXY_HOST: "http://{{ include "agentarea.fullname" . }}-mcp-manager"
MCP_CLIENT_TIMEOUT: "30"
{{- end }}