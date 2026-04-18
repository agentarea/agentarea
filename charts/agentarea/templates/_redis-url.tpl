{{/*
REDIS_URL env emitter.

Precedence:
  1. .Values.global.redis.existingSecret  -> valueFrom.secretKeyRef
     (key defaults to .Values.global.redis.existingSecretKey or "url")
  2. .Values.global.redis.url             -> literal value
  3. derived redis://:$(REDIS_PASSWORD)@$(REDIS_HOST):$(REDIS_PORT)
     (requires REDIS_PASSWORD/HOST/PORT from agentarea.redis.envs +
     agentarea.redis.secrets.envs to already be in the container env)

Emits exactly one `- name: REDIS_URL` entry. Include from every Deployment
that needs Redis, right after the redis.envs / redis.secrets.envs includes.
*/}}
{{- define "agentarea.redis.urlEnv" -}}
{{- $r := .Values.global.redis -}}
{{- if $r.existingSecret }}
- name: REDIS_URL
  valueFrom:
    secretKeyRef:
      name: {{ $r.existingSecret | quote }}
      key: {{ $r.existingSecretKey | default "url" | quote }}
{{- else if $r.url }}
- name: REDIS_URL
  value: {{ $r.url | quote }}
{{- else }}
- name: REDIS_URL
  value: "redis://:$(REDIS_PASSWORD)@$(REDIS_HOST):$(REDIS_PORT)"
{{- end }}
{{- end -}}
