{{- define "agentarea.storage.configVars" -}}
AWS_REGION: "{{ .Values.global.storage.region }}"
S3_BUCKET_NAME: "{{ .Values.global.storage.bucket }}"
AWS_ENDPOINT_URL: "http://{{ .Release.Name }}-minio:9000"
{{- end }}