# TODO: External Services Support (style)

## Current State

The chart currently uses simple conditionals to skip secret creation when services are disabled:
- `postgresql.enabled=false` → PostgreSQL secret not created
- `redis.enabled=false` → Redis secret not created
- `minio.enabled=false` → MinIO secret not created

**Problem**: This doesn't support connecting to external databases/services. If you disable the bundled PostgreSQL, you can't easily connect to an external one (RDS, Cloud SQL, etc.).

## Proposed Solution

Follow Airbyte's pattern with `type: internal/external` configuration:

```yaml
global:
  database:
    type: internal  # "internal" or "external"

    # Secret configuration
    secretName: ""  # If empty, auto-generates. Set to use existing secret.

    # Connection details (host auto-resolved when type=internal)
    host: ""
    port: 5432
    name: "agentarea"

    # Credentials (only used when generating secret)
    user: "postgres"
    password: ""

    # Secret key mappings (for reading from existing secrets)
    userSecretKey: "username"
    passwordSecretKey: "password"

  redis:
    type: internal  # "internal" or "external"
    secretName: ""
    host: ""
    port: 6379
    password: ""
    passwordSecretKey: "redis-password"

  storage:
    type: internal  # "internal" or "external"
    secretName: ""
    backend: "minio"  # "minio", "s3", "gcs"
    endpoint: ""
    bucket: "agentarea-documents"
    region: "us-east-1"
    accessKey: ""
    secretKey: ""
    accessKeySecretKey: "root-user"
    secretKeySecretKey: "root-password"
```

## Implementation Tasks

### 1. Update values.yaml
- [ ] Replace `global.secrets.*` with per-service configuration
- [ ] Add `type: internal/external` to database, redis, storage configs
- [ ] Add `secretName` field for BYO secret support
- [ ] Add secret key mappings for flexible secret structure

### 2. Update secrets.yaml
- [ ] Only create secrets when `type=internal` AND `secretName` is empty
- [ ] Use template includes for conditional secret data (like Airbyte)

### 3. Add helper templates
Create `_secrets.tpl` with helpers like:
```yaml
{{- define "agentarea.database.secretName" }}
{{- if .Values.global.database.secretName }}
  {{- .Values.global.database.secretName }}
{{- else }}
  {{- printf "%s-postgresql-secret" .Release.Name }}
{{- end }}
{{- end }}

{{- define "agentarea.database.userSecretKey" }}
{{- .Values.global.database.userSecretKey | default "username" }}
{{- end }}
```

### 4. Update env templates
Update `database.env.tpl`, `redis.env.tpl`, `storage.env.tpl` to use dynamic secret names and keys.

### 5. Update service discovery
Update `_service-discovery.tpl` to resolve hosts based on `type`:
```yaml
{{- define "agentarea.database.host" -}}
{{- if .Values.global.database.host -}}
  {{ .Values.global.database.host }}
{{- else if eq .Values.global.database.type "internal" -}}
  {{ .Release.Name }}-postgresql
{{- else -}}
  {{- fail "global.database.host is required when type=external" -}}
{{- end -}}
{{- end -}}
```

## Reference

See Airbyte Helm chart for implementation patterns:
- Database config: `charts/airbyte/templates/config/_database.tpl`
- Secrets: `charts/airbyte/templates/airbyte-secrets.yaml`
- Values: `charts/airbyte/values.yaml` → `global.database`

## Benefits

1. **Production-ready**: Easy to use managed databases (RDS, Cloud SQL, etc.)
2. **Flexible secrets**: BYO secret support for external secret managers
3. **Clean configuration**: Single `type` field controls behavior
4. **Backwards compatible**: Default `type: internal` preserves current behavior
