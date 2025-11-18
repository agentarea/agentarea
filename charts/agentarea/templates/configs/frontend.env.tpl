{{- define "agentarea.frontend.configVars" -}}
PORT: "3000"
NODE_ENV: "production"
NEXT_PUBLIC_API_URL: "http://{{ include "agentarea.fullname" . }}-backend:8000"
KRATOS_PUBLIC_URL: "http://ory-kratos-public:80"
KRATOS_ADMIN_URL: "http://ory-kratos-admin:80"
HYDRA_PUBLIC_URL: "http://ory-hydra-public:4444"
HYDRA_ADMIN_URL: "http://ory-hydra-admin:4445"
{{- end }}