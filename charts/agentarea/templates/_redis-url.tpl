{{/*
AGENTAREA_REDIS_URL env emitter.

Precedence:
  1. .Values.global.redis.existingSecret  -> valueFrom.secretKeyRef
     (key defaults to .Values.global.redis.existingSecretKey or "url")
  2. .Values.global.redis.url             -> literal value
  3. derived redis://:$(AGENTAREA_REDIS_PASSWORD)@$(AGENTAREA_REDIS_HOST):$(AGENTAREA_REDIS_PORT)
     (requires AGENTAREA_REDIS_PASSWORD/HOST/PORT from agentarea.redis.envs +
     agentarea.redis.secrets.envs to already be in the container env)

Emits exactly one `- name: AGENTAREA_REDIS_URL` entry. Include from every Deployment
that needs Redis, right after the redis.envs / redis.secrets.envs includes.
*/}}
{{- define "agentarea.redis.urlEnv" -}}
{{- $r := .Values.global.redis -}}
{{- if $r.existingSecret }}
- name: AGENTAREA_REDIS_URL
  valueFrom:
    secretKeyRef:
      name: {{ $r.existingSecret | quote }}
      key: {{ $r.existingSecretKey | default "url" | quote }}
{{- else if $r.url }}
- name: AGENTAREA_REDIS_URL
  value: {{ $r.url | quote }}
{{- else }}
- name: AGENTAREA_REDIS_URL
  value: "redis://:$(AGENTAREA_REDIS_PASSWORD)@$(AGENTAREA_REDIS_HOST):$(AGENTAREA_REDIS_PORT)"
{{- end }}
{{- end -}}
