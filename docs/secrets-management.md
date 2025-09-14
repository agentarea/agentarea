# Secrets Management

<Info>
Proper secrets management is crucial for secure AgentArea deployments. This guide covers various secret storage solutions, best practices, and integration patterns for both development and production environments.
</Info>

## 🔐 Secrets Overview

AgentArea requires various types of secrets for secure operation:

<CardGroup cols={2}>
  <Card title="Database Credentials" icon="database">
    PostgreSQL connection strings, usernames, and passwords
  </Card>
  
  <Card title="API Keys & Tokens" icon="key">
    JWT secrets, OpenAI API keys, third-party service tokens
  </Card>
  
  <Card title="Infrastructure Secrets" icon="server">
    TLS certificates, SSH keys, cloud provider credentials
  </Card>
  
  <Card title="Application Secrets" icon="shield">
    Encryption keys, webhook secrets, session keys
  </Card>
</CardGroup>

## 🏗️ Secret Storage Solutions

### Local Development

<Tabs>
  <Tab title="Environment Files">
    **Simple .env files for local development**
    
    ```bash
    # .env.local
    DATABASE_URL=postgresql://user:pass@localhost:5432/agentarea
    JWT_SECRET_KEY=your-local-secret-key
    OPENAI_API_KEY=sk-your-openai-key
    REDIS_URL=redis://localhost:6379
    
    # Load in application
    export $(cat .env.local | xargs)
    ```
    
    <Warning>
    Never commit .env files to version control. Add to .gitignore immediately.
    </Warning>
  </Tab>
  
  <Tab title="Local Secret Manager">
    **Using pass or similar tools**
    
    ```bash
    # Install pass (password store)
    brew install pass  # macOS
    sudo apt install pass  # Ubuntu
    
    # Initialize
    pass init your-gpg-key
    
    # Store secrets
    pass insert agentarea/database-url
    pass insert agentarea/jwt-secret
    pass insert agentarea/openai-key
    
    # Retrieve in scripts
    export DATABASE_URL=$(pass show agentarea/database-url)
    export JWT_SECRET_KEY=$(pass show agentarea/jwt-secret)
    ```
  </Tab>
</Tabs>

### Production Solutions

<Tabs>
  <Tab title="HashiCorp Vault">
    **Enterprise-grade secret management**
    
    ```yaml
    # vault-config.yml
    vault:
      server: "https://vault.company.com"
      auth_method: "kubernetes"
      role: "agentarea-prod"
      secrets_path: "secret/agentarea"
    
    secrets:
      database:
        path: "secret/agentarea/database"
        keys: ["url", "username", "password"]
      api_keys:
        path: "secret/agentarea/api-keys"
        keys: ["openai", "jwt_secret"]
    ```
    
    ```python
    # Python Vault integration
    import hvac
    
    def get_vault_secrets():
        client = hvac.Client(url='https://vault.company.com')
        
        # Kubernetes auth
        with open('/var/run/secrets/kubernetes.io/serviceaccount/token') as f:
            jwt = f.read()
        
        client.auth.kubernetes.login(
            role='agentarea-prod',
            jwt=jwt
        )
        
        # Read secrets
        db_secrets = client.secrets.kv.v2.read_secret_version(
            path='agentarea/database'
        )['data']['data']
        
        return {
            'DATABASE_URL': db_secrets['url'],
            'JWT_SECRET_KEY': db_secrets['jwt_secret']
        }
    ```
  </Tab>
  
  <Tab title="AWS Secrets Manager">
    **AWS-native secret storage**
    
    ```json
    {
      "SecretName": "agentarea/prod/database",
      "SecretString": {
        "username": "agentarea_user",
        "password": "super-secure-password",
        "host": "prod-db.cluster-xyz.us-west-2.rds.amazonaws.com",
        "port": 5432,
        "dbname": "agentarea"
      }
    }
    ```
    
    ```python
    # Python AWS Secrets Manager integration
    import boto3
    import json
    
    def get_aws_secrets():
        session = boto3.session.Session()
        client = session.client('secretsmanager', region_name='us-west-2')
        
        try:
            response = client.get_secret_value(SecretId='agentarea/prod/database')
            secret = json.loads(response['SecretString'])
            
            return {
                'DATABASE_URL': f"postgresql://{secret['username']}:{secret['password']}@{secret['host']}:{secret['port']}/{secret['dbname']}"
            }
        except Exception as e:
            print(f"Error retrieving secret: {e}")
            raise
    ```
  </Tab>
  
  <Tab title="Azure Key Vault">
    **Microsoft Azure secret management**
    
    ```python
    # Azure Key Vault integration
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient
    
    def get_azure_secrets():
        credential = DefaultAzureCredential()
        client = SecretClient(
            vault_url="https://agentarea-vault.vault.azure.net/",
            credential=credential
        )
        
        secrets = {}
        secret_names = [
            "database-url",
            "jwt-secret-key", 
            "openai-api-key",
            "redis-url"
        ]
        
        for name in secret_names:
            try:
                secret = client.get_secret(name)
                env_name = name.upper().replace('-', '_')
                secrets[env_name] = secret.value
            except Exception as e:
                print(f"Error retrieving {name}: {e}")
        
        return secrets
    ```
  </Tab>
  
  <Tab title="Google Secret Manager">
    **Google Cloud secret storage**
    
    ```python
    # Google Secret Manager integration
    from google.cloud import secretmanager
    
    def get_gcp_secrets():
        client = secretmanager.SecretManagerServiceClient()
        project_id = "your-project-id"
        
        secrets = {}
        secret_configs = [
            ("database-url", "DATABASE_URL"),
            ("jwt-secret", "JWT_SECRET_KEY"),
            ("openai-key", "OPENAI_API_KEY")
        ]
        
        for secret_name, env_var in secret_configs:
            name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
            
            try:
                response = client.access_secret_version(request={"name": name})
                secrets[env_var] = response.payload.data.decode("UTF-8")
            except Exception as e:
                print(f"Error retrieving {secret_name}: {e}")
        
        return secrets
    ```
  </Tab>
</Tabs>

## 🐳 Docker Integration

### Docker Secrets

<Tabs>
  <Tab title="Docker Compose Secrets">
    ```yaml
    # docker-compose.yml
    version: '3.8'
    
    secrets:
      db_password:
        file: ./secrets/db_password.txt
      jwt_secret:
        file: ./secrets/jwt_secret.txt
      openai_key:
        external: true
        name: agentarea_openai_key
    
    services:
      agentarea-api:
        image: agentarea/api:latest
        secrets:
          - db_password
          - jwt_secret
          - openai_key
        environment:
          - DATABASE_URL_FILE=/run/secrets/db_password
          - JWT_SECRET_KEY_FILE=/run/secrets/jwt_secret
          - OPENAI_API_KEY_FILE=/run/secrets/openai_key
    ```
  </Tab>
  
  <Tab title="External Secret Files">
    ```bash
    # Create external secrets
    echo "your-openai-key" | docker secret create agentarea_openai_key -
    echo "your-jwt-secret" | docker secret create agentarea_jwt_secret -
    
    # Update compose file to use external secrets
    docker-compose up -d
    ```
  </Tab>
  
  <Tab title="Runtime Secret Loading">
    ```python
    # app/secrets.py
    import os
    
    def load_secret_from_file(file_path: str) -> str:
        """Load secret from Docker secrets file"""
        try:
            with open(file_path, 'r') as f:
                return f.read().strip()
        except FileNotFoundError:
            return None
    
    def get_secret(env_var: str) -> str:
        """Get secret from environment or file"""
        # Try environment variable first
        value = os.getenv(env_var)
        if value:
            return value
        
        # Try secret file
        file_path = os.getenv(f"{env_var}_FILE")
        if file_path:
            return load_secret_from_file(file_path)
        
        raise ValueError(f"Secret {env_var} not found")
    
    # Usage
    DATABASE_URL = get_secret("DATABASE_URL")
    JWT_SECRET_KEY = get_secret("JWT_SECRET_KEY")
    ```
  </Tab>
</Tabs>

## ☸️ Kubernetes Integration

### Native Kubernetes Secrets

<Tabs>
  <Tab title="Secret Creation">
    ```bash
    # Create secrets from literals
    kubectl create secret generic agentarea-secrets \
      --from-literal=database-url="postgresql://user:pass@host:5432/db" \
      --from-literal=jwt-secret="your-jwt-secret" \
      --from-literal=openai-key="sk-your-key"
    
    # Create secrets from files
    kubectl create secret generic agentarea-tls \
      --from-file=tls.crt=./certs/tls.crt \
      --from-file=tls.key=./certs/tls.key
    
    # Create secrets from env file
    kubectl create secret generic agentarea-env \
      --from-env-file=.env.production
    ```
  </Tab>
  
  <Tab title="Pod Configuration">
    ```yaml
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: agentarea-api
    spec:
      template:
        spec:
          containers:
          - name: api
            image: agentarea/api:latest
            env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: agentarea-secrets
                  key: database-url
            - name: JWT_SECRET_KEY
              valueFrom:
                secretKeyRef:
                  name: agentarea-secrets
                  key: jwt-secret
            
            # Mount secrets as files
            volumeMounts:
            - name: secret-volume
              mountPath: "/etc/secrets"
              readOnly: true
          
          volumes:
          - name: secret-volume
            secret:
              secretName: agentarea-secrets
              items:
              - key: openai-key
                path: openai-api-key
    ```
  </Tab>
  
  <Tab title="External Secrets Operator">
    ```yaml
    # Install External Secrets Operator
    helm repo add external-secrets https://charts.external-secrets.io
    helm install external-secrets external-secrets/external-secrets -n external-secrets-system --create-namespace
    
    # Configure secret store
    apiVersion: external-secrets.io/v1beta1
    kind: SecretStore
    metadata:
      name: vault-backend
    spec:
      provider:
        vault:
          server: "https://vault.company.com"
          path: "secret"
          version: "v2"
          auth:
            kubernetes:
              mountPath: "kubernetes"
              role: "agentarea"
    
    # Create external secret
    apiVersion: external-secrets.io/v1beta1
    kind: ExternalSecret
    metadata:
      name: agentarea-secrets
    spec:
      refreshInterval: 15s
      secretStoreRef:
        name: vault-backend
        kind: SecretStore
      target:
        name: agentarea-secrets
        creationPolicy: Owner
      data:
      - secretKey: database-url
        remoteRef:
          key: agentarea/database
          property: url
      - secretKey: jwt-secret
        remoteRef:
          key: agentarea/auth
          property: jwt_secret
    ```
  </Tab>
</Tabs>

## 🔄 Secret Rotation

### Automated Rotation

<Accordion>
  <AccordionItem title="Database Password Rotation">
    ```python
    # scripts/rotate_db_password.py
    import secrets
    import string
    import psycopg2
    from vault_client import VaultClient
    
    def generate_secure_password(length=32):
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        return ''.join(secrets.choice(alphabet) for _ in range(length))
    
    def rotate_database_password():
        vault = VaultClient()
        
        # Generate new password
        new_password = generate_secure_password()
        
        # Update database user
        conn = psycopg2.connect(vault.get_secret("database/admin_url"))
        cur = conn.cursor()
        
        cur.execute(
            "ALTER USER agentarea_user PASSWORD %s",
            (new_password,)
        )
        conn.commit()
        conn.close()
        
        # Update secret in Vault
        vault.write_secret("agentarea/database", {
            "password": new_password,
            "rotated_at": datetime.utcnow().isoformat()
        })
        
        print("Database password rotated successfully")
    
    if __name__ == "__main__":
        rotate_database_password()
    ```
  </AccordionItem>
  
  <AccordionItem title="API Key Rotation">
    ```bash
    #!/bin/bash
    # scripts/rotate_api_keys.sh
    
    # Rotate JWT secret
    NEW_JWT_SECRET=$(openssl rand -base64 32)
    
    # Update in secret store
    vault kv put secret/agentarea/auth jwt_secret="$NEW_JWT_SECRET"
    
    # Trigger rolling deployment
    kubectl rollout restart deployment/agentarea-api
    
    # Wait for deployment
    kubectl rollout status deployment/agentarea-api
    
    echo "JWT secret rotated and deployment updated"
    ```
  </AccordionItem>
  
  <AccordionItem title="TLS Certificate Rotation">
    ```yaml
    # cert-manager automatic renewal
    apiVersion: cert-manager.io/v1
    kind: Certificate
    metadata:
      name: agentarea-tls
    spec:
      secretName: agentarea-tls-secret
      duration: 2160h # 90 days
      renewBefore: 360h # 15 days before expiry
      subject:
        organizations:
        - agentarea
      dnsNames:
      - agentarea.example.com
      - api.agentarea.example.com
      issuerRef:
        name: letsencrypt-prod
        kind: ClusterIssuer
    ```
  </AccordionItem>
</Accordion>

## 🛡️ Security Best Practices

### Secret Lifecycle Management

<CardGroup cols={2}>
  <Card title="Generation" icon="key">
    - Use cryptographically secure random generators
    - Enforce minimum complexity requirements
    - Generate unique secrets per environment
    - Document secret purposes and ownership
  </Card>
  
  <Card title="Storage" icon="shield">
    - Never store secrets in code or configs
    - Use encryption at rest and in transit
    - Implement proper access controls
    - Audit secret access and modifications
  </Card>
  
  <Card title="Distribution" icon="share">
    - Use secure channels for secret delivery
    - Implement just-in-time access patterns
    - Minimize secret exposure time
    - Use short-lived tokens when possible
  </Card>
  
  <Card title="Rotation" icon="refresh-cw">
    - Implement regular rotation schedules
    - Automate rotation where possible
    - Test rotation procedures regularly
    - Have rollback procedures ready
  </Card>
</CardGroup>

### Access Control

<Tabs>
  <Tab title="RBAC Policies">
    ```yaml
    # Kubernetes RBAC for secrets
    apiVersion: rbac.authorization.k8s.io/v1
    kind: Role
    metadata:
      name: agentarea-secrets-reader
    rules:
    - apiGroups: [""]
      resources: ["secrets"]
      verbs: ["get", "list"]
      resourceNames: ["agentarea-secrets"]
    
    ---
    apiVersion: rbac.authorization.k8s.io/v1
    kind: RoleBinding
    metadata:
      name: agentarea-secrets-binding
    subjects:
    - kind: ServiceAccount
      name: agentarea-api
    roleRef:
      kind: Role
      name: agentarea-secrets-reader
      apiGroup: rbac.authorization.k8s.io
    ```
  </Tab>
  
  <Tab title="Vault Policies">
    ```hcl
    # Vault policy for AgentArea
    path "secret/data/agentarea/*" {
      capabilities = ["read"]
    }
    
    path "secret/data/agentarea/database" {
      capabilities = ["read", "update"]
    }
    
    path "auth/token/lookup-self" {
      capabilities = ["read"]
    }
    ```
  </Tab>
  
  <Tab title="IAM Policies">
    ```json
    {
      "Version": "2012-10-17",
      "Statement": [
        {
          "Effect": "Allow",
          "Action": [
            "secretsmanager:GetSecretValue"
          ],
          "Resource": [
            "arn:aws:secretsmanager:*:*:secret:agentarea/*"
          ]
        },
        {
          "Effect": "Allow",
          "Action": [
            "secretsmanager:DescribeSecret"
          ],
          "Resource": "*"
        }
      ]
    }
    ```
  </Tab>
</Tabs>

## 📊 Monitoring & Auditing

### Secret Access Monitoring

<Accordion>
  <AccordionItem title="Vault Audit Logs">
    ```bash
    # Enable Vault audit logging
    vault audit enable file file_path=/vault/logs/audit.log
    
    # Query audit logs
    cat /vault/logs/audit.log | jq '.request.path' | grep "agentarea"
    
    # Monitor secret access
    tail -f /vault/logs/audit.log | jq 'select(.request.path | contains("agentarea"))'
    ```
  </AccordionItem>
  
  <AccordionItem title="Kubernetes Events">
    ```bash
    # Monitor secret-related events
    kubectl get events --field-selector involvedObject.kind=Secret
    
    # Watch for secret modifications
    kubectl get events --watch --field-selector reason=SecretUpdated
    
    # Audit secret access
    kubectl logs -l app=agentarea-api | grep "secret"
    ```
  </AccordionItem>
  
  <AccordionItem title="Application Metrics">
    ```python
    # Prometheus metrics for secret usage
    from prometheus_client import Counter, Histogram
    
    secret_access_counter = Counter(
        'agentarea_secret_access_total',
        'Total secret access attempts',
        ['secret_type', 'status']
    )
    
    secret_rotation_time = Histogram(
        'agentarea_secret_rotation_duration_seconds',
        'Time spent rotating secrets',
        ['secret_type']
    )
    
    def get_secret_with_metrics(secret_name):
        try:
            secret = get_secret(secret_name)
            secret_access_counter.labels(
                secret_type=secret_name,
                status='success'
            ).inc()
            return secret
        except Exception as e:
            secret_access_counter.labels(
                secret_type=secret_name,
                status='error'
            ).inc()
            raise
    ```
  </AccordionItem>
</Accordion>

## 🚨 Incident Response

### Secret Compromise Response

<Steps>
  <Step title="Immediate Actions">
    1. **Identify scope** - Determine which secrets are compromised
    2. **Revoke access** - Immediately disable compromised credentials
    3. **Rotate secrets** - Generate new secrets for affected systems
    4. **Update applications** - Deploy new secrets to running systems
  </Step>
  
  <Step title="Investigation">
    1. **Audit logs** - Review access logs for unauthorized usage
    2. **Timeline analysis** - Determine when compromise occurred
    3. **Impact assessment** - Identify affected systems and data
    4. **Root cause** - Understand how the compromise happened
  </Step>
  
  <Step title="Recovery">
    1. **System validation** - Ensure all systems are using new secrets
    2. **Monitoring** - Enhanced monitoring for suspicious activity
    3. **Documentation** - Update incident documentation
    4. **Process improvement** - Strengthen security procedures
  </Step>
</Steps>

### Emergency Procedures

```bash
# Emergency secret rotation script
#!/bin/bash
set -e

echo "🚨 EMERGENCY SECRET ROTATION"
echo "This will rotate ALL AgentArea secrets"
read -p "Are you sure? (yes/NO): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Aborted"
    exit 1
fi

# Rotate database password
./scripts/rotate_db_password.py

# Rotate JWT secret
./scripts/rotate_jwt_secret.sh

# Rotate API keys
./scripts/rotate_api_keys.sh

# Update Kubernetes secrets
kubectl delete secret agentarea-secrets
kubectl create secret generic agentarea-secrets \
  --from-literal=database-url="$(vault kv get -field=url secret/agentarea/database)" \
  --from-literal=jwt-secret="$(vault kv get -field=jwt_secret secret/agentarea/auth)"

# Rolling restart
kubectl rollout restart deployment/agentarea-api
kubectl rollout restart deployment/agentarea-frontend

echo "✅ Emergency rotation complete"
```

---

<Note>
**Security is a shared responsibility.** Regular secret rotation, proper access controls, and monitoring are essential for maintaining a secure AgentArea deployment. Always follow the principle of least privilege and implement defense-in-depth strategies.
</Note>