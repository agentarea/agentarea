# Production Deployment Guide

<Info>
This guide provides detailed instructions for deploying AgentArea using Docker and Kubernetes. For infrastructure overview and monitoring setup, see the [Infrastructure](/infrastructure) and [Monitoring](/monitoring) sections.
</Info>

## 🎯 Deployment Strategies

<CardGroup cols={2}>
  <Card title="Docker Compose" icon="docker">
    **Best for**: Small to medium deployments, single-server setups
    - Quick setup and deployment
    - Integrated service orchestration
    - Built-in networking and volumes
    - Perfect for staging environments
  </Card>
  
  <Card title="Kubernetes" icon="kubernetes">
    **Best for**: Enterprise deployments, high availability
    - Auto-scaling and load balancing
    - Rolling updates and rollbacks
    - Service discovery and networking
    - Production-grade orchestration
  </Card>
</CardGroup>

## 🐳 Docker Compose Deployment

### Prerequisites

- Docker Engine 20.0+
- Docker Compose 2.0+
- 4GB+ RAM, 20GB+ storage
- Valid domain name with SSL certificate

### Production Docker Compose

<Tabs>
  <Tab title="docker-compose.prod.yml">
    ```yaml
    version: '3.8'
    
    services:
      agentarea-api:
        image: agentarea/api:latest
        restart: unless-stopped
        environment:
          - DATABASE_URL=${DATABASE_URL}
          - REDIS_URL=${REDIS_URL}
          - JWT_SECRET_KEY=${JWT_SECRET_KEY}
          - ENVIRONMENT=production
        networks:
          - agentarea-network
        depends_on:
          - postgres
          - redis
        healthcheck:
          test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
          interval: 30s
          timeout: 10s
          retries: 3
    
      agentarea-frontend:
        image: agentarea/frontend:latest
        restart: unless-stopped
        environment:
          - NEXT_PUBLIC_API_URL=${API_URL}
          - NEXT_PUBLIC_ENVIRONMENT=production
        networks:
          - agentarea-network
        depends_on:
          - agentarea-api
    
      mcp-manager:
        image: agentarea/mcp-manager:latest
        restart: unless-stopped
        environment:
          - SERVER_PORT=8001
          - DATABASE_URL=${DATABASE_URL}
          - LOG_LEVEL=info
        networks:
          - agentarea-network
        volumes:
          - mcp-data:/app/data
        privileged: true
    
      postgres:
        image: postgres:15-alpine
        restart: unless-stopped
        environment:
          - POSTGRES_DB=${POSTGRES_DB}
          - POSTGRES_USER=${POSTGRES_USER}
          - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
        volumes:
          - postgres-data:/var/lib/postgresql/data
          - ./backups:/backups
        networks:
          - agentarea-network
        command: >
          postgres -c max_connections=200
                   -c shared_buffers=256MB
                   -c effective_cache_size=1GB
    
      redis:
        image: redis:7-alpine
        restart: unless-stopped
        command: redis-server --appendonly yes --maxmemory 512mb
        volumes:
          - redis-data:/data
        networks:
          - agentarea-network
    
      traefik:
        image: traefik:v3.0
        restart: unless-stopped
        command:
          - "--api.dashboard=true"
          - "--providers.docker=true"
          - "--providers.docker.exposedbydefault=false"
          - "--entrypoints.web.address=:80"
          - "--entrypoints.websecure.address=:443"
          - "--certificatesresolvers.letsencrypt.acme.tlschallenge=true"
          - "--certificatesresolvers.letsencrypt.acme.email=${ACME_EMAIL}"
          - "--certificatesresolvers.letsencrypt.acme.storage=/letsencrypt/acme.json"
        ports:
          - "80:80"
          - "443:443"
          - "8080:8080"
        volumes:
          - /var/run/docker.sock:/var/run/docker.sock:ro
          - letsencrypt-data:/letsencrypt
        networks:
          - agentarea-network
        labels:
          - "traefik.enable=true"
          - "traefik.http.routers.api.rule=Host(`traefik.${DOMAIN}`)"
          - "traefik.http.routers.api.tls.certresolver=letsencrypt"
          - "traefik.http.routers.api.service=api@internal"
    
    volumes:
      postgres-data:
      redis-data:
      mcp-data:
      letsencrypt-data:
    
    networks:
      agentarea-network:
        driver: bridge
    ```
  </Tab>
  
  <Tab title=".env.production">
    ```bash
    # Domain and SSL
    DOMAIN=yourdomain.com
    ACME_EMAIL=admin@yourdomain.com
    API_URL=https://api.yourdomain.com
    
    # Database Configuration
    POSTGRES_DB=agentarea
    POSTGRES_USER=agentarea
    POSTGRES_PASSWORD=your-secure-password
    DATABASE_URL=postgresql://agentarea:your-secure-password@postgres:5432/agentarea
    
    # Redis Configuration
    REDIS_URL=redis://redis:6379
    
    # Security
    JWT_SECRET_KEY=your-256-bit-secret-key
    
    # Application Settings
    ENVIRONMENT=production
    LOG_LEVEL=info
    ```
  </Tab>
</Tabs>

### Deployment Steps

<Steps>
  <Step title="Server Preparation">
    ```bash
    # Update system
    sudo apt update && sudo apt upgrade -y
    
    # Install Docker and Docker Compose
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    
    # Install Docker Compose
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    ```
  </Step>
  
  <Step title="Configure Environment">
    ```bash
    # Clone production configuration
    git clone https://github.com/agentarea/agentarea-deploy.git
    cd agentarea-deploy
    
    # Configure environment variables
    cp .env.example .env.production
    nano .env.production  # Edit with your values
    ```
  </Step>
  
  <Step title="Deploy Services">
    ```bash
    # Pull latest images
    docker-compose -f docker-compose.prod.yml pull
    
    # Start services
    docker-compose -f docker-compose.prod.yml --env-file .env.production up -d
    
    # Verify deployment
    docker-compose -f docker-compose.prod.yml ps
    ```
  </Step>
  
  <Step title="Configure SSL & DNS">
    ```bash
    # Point DNS records to your server
    # A record: yourdomain.com -> YOUR_SERVER_IP
    # A record: api.yourdomain.com -> YOUR_SERVER_IP
    # A record: traefik.yourdomain.com -> YOUR_SERVER_IP
    
    # SSL certificates will be automatically issued by Let's Encrypt
    ```
  </Step>
</Steps>

## ☸️ Kubernetes Deployment

### Prerequisites

- Kubernetes cluster 1.24+
- kubectl configured
- Helm 3.0+
- Persistent volume provisioner
- Ingress controller

### Helm Chart Deployment

<Tabs>
  <Tab title="values.yaml">
    ```yaml
    # AgentArea Helm Chart Configuration
    global:
      domain: yourdomain.com
      environment: production
      imageRegistry: docker.io/agentarea
    
    api:
      image:
        repository: agentarea/api
        tag: "latest"
        pullPolicy: IfNotPresent
      
      replicas: 3
      resources:
        requests:
          cpu: 500m
          memory: 1Gi
        limits:
          cpu: 2
          memory: 4Gi
      
      autoscaling:
        enabled: true
        minReplicas: 3
        maxReplicas: 10
        targetCPUUtilizationPercentage: 70
    
    frontend:
      image:
        repository: agentarea/frontend
        tag: "latest"
      
      replicas: 2
      resources:
        requests:
          cpu: 100m
          memory: 256Mi
        limits:
          cpu: 500m
          memory: 512Mi
    
    mcpManager:
      image:
        repository: agentarea/mcp-manager
        tag: "latest"
      
      replicas: 2
      resources:
        requests:
          cpu: 250m
          memory: 512Mi
        limits:
          cpu: 1
          memory: 2Gi
    
    postgresql:
      enabled: true
      auth:
        database: agentarea
        username: agentarea
        password: "your-secure-password"
      
      primary:
        resources:
          requests:
            cpu: 500m
            memory: 1Gi
          limits:
            cpu: 2
            memory: 4Gi
        
        persistence:
          enabled: true
          size: 100Gi
          storageClass: "fast-ssd"
    
    redis:
      enabled: true
      auth:
        enabled: false
      
      master:
        resources:
          requests:
            cpu: 100m
            memory: 256Mi
          limits:
            cpu: 500m
            memory: 512Mi
        
        persistence:
          enabled: true
          size: 20Gi
    
    ingress:
      enabled: true
      className: "nginx"
      annotations:
        cert-manager.io/cluster-issuer: "letsencrypt-prod"
        nginx.ingress.kubernetes.io/ssl-redirect: "true"
      
      hosts:
        - host: yourdomain.com
          paths:
            - path: /
              pathType: Prefix
              service: frontend
        - host: api.yourdomain.com
          paths:
            - path: /
              pathType: Prefix
              service: api
      
      tls:
        - secretName: agentarea-tls
          hosts:
            - yourdomain.com
            - api.yourdomain.com
    
    monitoring:
      enabled: true
      prometheus:
        enabled: true
      grafana:
        enabled: true
    ```
  </Tab>
  
  <Tab title="Deployment Commands">
    ```bash
    # Add AgentArea Helm repository
    helm repo add agentarea https://charts.agentarea.ai
    helm repo update
    
    # Create namespace
    kubectl create namespace agentarea
    
    # Install cert-manager for SSL
    kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml
    
    # Create cluster issuer
    kubectl apply -f - <<EOF
    apiVersion: cert-manager.io/v1
    kind: ClusterIssuer
    metadata:
      name: letsencrypt-prod
    spec:
      acme:
        server: https://acme-v02.api.letsencrypt.org/directory
        email: admin@yourdomain.com
        privateKeySecretRef:
          name: letsencrypt-prod
        solvers:
        - http01:
            ingress:
              class: nginx
    EOF
    
    # Install AgentArea
    helm install agentarea agentarea/agentarea \
      --namespace agentarea \
      --values values.yaml \
      --wait
    
    # Verify deployment
    kubectl get pods -n agentarea
    kubectl get ingress -n agentarea
    ```
  </Tab>
</Tabs>

### Kubernetes Security Configuration

<Accordion>
  <AccordionItem title="Network Policies">
    ```yaml
    apiVersion: networking.k8s.io/v1
    kind: NetworkPolicy
    metadata:
      name: agentarea-network-policy
      namespace: agentarea
    spec:
      podSelector: {}
      policyTypes:
      - Ingress
      - Egress
      ingress:
      - from:
        - namespaceSelector:
            matchLabels:
              name: ingress-nginx
      - from:
        - namespaceSelector:
            matchLabels:
              name: agentarea
      egress:
      - to: []
        ports:
        - protocol: TCP
          port: 53
        - protocol: UDP
          port: 53
      - to:
        - namespaceSelector:
            matchLabels:
              name: agentarea
    ```
  </AccordionItem>
  
  <AccordionItem title="Pod Security Policy">
    ```yaml
    apiVersion: policy/v1beta1
    kind: PodSecurityPolicy
    metadata:
      name: agentarea-psp
    spec:
      privileged: false
      allowPrivilegeEscalation: false
      requiredDropCapabilities:
        - ALL
      volumes:
        - 'configMap'
        - 'emptyDir'
        - 'projected'
        - 'secret'
        - 'downwardAPI'
        - 'persistentVolumeClaim'
      runAsUser:
        rule: 'MustRunAsNonRoot'
      seLinux:
        rule: 'RunAsAny'
      fsGroup:
        rule: 'RunAsAny'
    ```
  </AccordionItem>
</Accordion>

## ☁️ Cloud Platform Deployment

### AWS ECS with Fargate

<Tabs>
  <Tab title="Task Definition">
    ```json
    {
      "family": "agentarea-api",
      "networkMode": "awsvpc",
      "requiresCompatibilities": ["FARGATE"],
      "cpu": "1024",
      "memory": "2048",
      "executionRoleArn": "arn:aws:iam::ACCOUNT:role/ecsTaskExecutionRole",
      "taskRoleArn": "arn:aws:iam::ACCOUNT:role/agentareaTaskRole",
      "containerDefinitions": [
        {
          "name": "agentarea-api",
          "image": "agentarea/api:latest",
          "portMappings": [
            {
              "containerPort": 8000,
              "protocol": "tcp"
            }
          ],
          "environment": [
            {
              "name": "ENVIRONMENT",
              "value": "production"
            }
          ],
          "secrets": [
            {
              "name": "DATABASE_URL",
              "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:agentarea/database-url"
            }
          ],
          "logConfiguration": {
            "logDriver": "awslogs",
            "options": {
              "awslogs-group": "/ecs/agentarea-api",
              "awslogs-region": "us-west-2",
              "awslogs-stream-prefix": "ecs"
            }
          }
        }
      ]
    }
    ```
  </Tab>
  
  <Tab title="Terraform Configuration">
    ```hcl
    # VPC and Networking
    module "vpc" {
      source = "terraform-aws-modules/vpc/aws"
      
      name = "agentarea-vpc"
      cidr = "10.0.0.0/16"
      
      azs             = ["us-west-2a", "us-west-2b", "us-west-2c"]
      private_subnets = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
      public_subnets  = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]
      
      enable_nat_gateway = true
      enable_vpn_gateway = false
    }
    
    # RDS PostgreSQL
    resource "aws_db_instance" "agentarea" {
      identifier     = "agentarea-db"
      engine         = "postgres"
      engine_version = "15.4"
      instance_class = "db.r6g.large"
      
      allocated_storage     = 100
      max_allocated_storage = 1000
      storage_encrypted     = true
      
      db_name  = "agentarea"
      username = "agentarea"
      password = random_password.db_password.result
      
      vpc_security_group_ids = [aws_security_group.rds.id]
      db_subnet_group_name   = aws_db_subnet_group.agentarea.name
      
      backup_retention_period = 7
      backup_window          = "03:00-04:00"
      maintenance_window     = "sun:04:00-sun:05:00"
      
      skip_final_snapshot = false
      deletion_protection = true
    }
    
    # ECS Cluster
    resource "aws_ecs_cluster" "agentarea" {
      name = "agentarea-cluster"
      
      setting {
        name  = "containerInsights"
        value = "enabled"
      }
    }
    
    # Application Load Balancer
    resource "aws_lb" "agentarea" {
      name               = "agentarea-alb"
      internal           = false
      load_balancer_type = "application"
      security_groups    = [aws_security_group.alb.id]
      subnets           = module.vpc.public_subnets
      
      enable_deletion_protection = true
    }
    ```
  </Tab>
</Tabs>

### Google Cloud Run

```yaml
# deploy.yaml
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: agentarea-api
  annotations:
    run.googleapis.com/ingress: all
    run.googleapis.com/execution-environment: gen2
spec:
  template:
    metadata:
      annotations:
        run.googleapis.com/cpu-throttling: "false"
        run.googleapis.com/memory: "2Gi"
        run.googleapis.com/cpu: "2"
        run.googleapis.com/max-scale: "100"
        run.googleapis.com/min-scale: "1"
    spec:
      containers:
      - image: gcr.io/PROJECT_ID/agentarea-api:latest
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: agentarea-secrets
              key: database-url
        resources:
          limits:
            cpu: "2"
            memory: "2Gi"
```

## 📊 Monitoring & Observability

### Prometheus & Grafana

<Tabs>
  <Tab title="Prometheus Configuration">
    ```yaml
    # prometheus.yml
    global:
      scrape_interval: 15s
      evaluation_interval: 15s
    
    rule_files:
      - "agentarea_rules.yml"
    
    scrape_configs:
      - job_name: 'agentarea-api'
        static_configs:
          - targets: ['agentarea-api:8000']
        metrics_path: '/metrics'
        scrape_interval: 5s
    
      - job_name: 'mcp-manager'
        static_configs:
          - targets: ['mcp-manager:8001']
        metrics_path: '/metrics'
        scrape_interval: 10s
    
      - job_name: 'postgres-exporter'
        static_configs:
          - targets: ['postgres-exporter:9187']
    
      - job_name: 'redis-exporter'
        static_configs:
          - targets: ['redis-exporter:9121']
    ```
  </Tab>
  
  <Tab title="Grafana Dashboard">
    ```json
    {
      "dashboard": {
        "title": "AgentArea Production Dashboard",
        "panels": [
          {
            "title": "API Response Time",
            "type": "graph",
            "targets": [
              {
                "expr": "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))",
                "legendFormat": "95th percentile"
              }
            ]
          },
          {
            "title": "Active Agents",
            "type": "stat",
            "targets": [
              {
                "expr": "agentarea_active_agents_total",
                "legendFormat": "Active Agents"
              }
            ]
          },
          {
            "title": "Error Rate",
            "type": "graph",
            "targets": [
              {
                "expr": "rate(http_requests_total{status=~\"5..\"}[5m])",
                "legendFormat": "5xx errors"
              }
            ]
          }
        ]
      }
    }
    ```
  </Tab>
</Tabs>

### Alerting Rules

```yaml
# agentarea_rules.yml
groups:
- name: agentarea.rules
  rules:
  - alert: HighErrorRate
    expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.1
    for: 2m
    labels:
      severity: critical
    annotations:
      summary: "High error rate detected"
      description: "Error rate is {{ $value }} for the last 5 minutes"

  - alert: DatabaseConnectionFailure
    expr: agentarea_database_connections_failed_total > 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Database connection failures"
      description: "Database connections are failing"

  - alert: HighMemoryUsage
    expr: (container_memory_usage_bytes / container_spec_memory_limit_bytes) > 0.9
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High memory usage"
      description: "Memory usage is above 90%"
```

## 🔄 CI/CD Pipeline

### GitHub Actions

```yaml
# .github/workflows/deploy.yml
name: Deploy to Production

on:
  push:
    branches: [main]
    tags: ['v*']

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - name: Run tests
      run: |
        make test
        make security-test

  build:
    needs: test
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - name: Build and push Docker images
      run: |
        docker build -t agentarea/api:${{ github.sha }} .
        docker push agentarea/api:${{ github.sha }}

  deploy:
    needs: build
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
    - name: Deploy to Kubernetes
      run: |
        helm upgrade agentarea agentarea/agentarea \
          --set api.image.tag=${{ github.sha }} \
          --namespace agentarea
```

## 🔧 Maintenance & Operations

### Database Maintenance

<Accordion>
  <AccordionItem title="Backup Strategy">
    ```bash
    # Automated backup script
    #!/bin/bash
    BACKUP_DIR="/backups/postgresql"
    DATE=$(date +%Y%m%d_%H%M%S)
    
    # Create backup
    pg_dump -h postgres -U agentarea agentarea | gzip > "$BACKUP_DIR/agentarea_$DATE.sql.gz"
    
    # Retain backups for 30 days
    find $BACKUP_DIR -name "*.sql.gz" -mtime +30 -delete
    
    # Upload to S3
    aws s3 cp "$BACKUP_DIR/agentarea_$DATE.sql.gz" s3://agentarea-backups/
    ```
  </AccordionItem>
  
  <AccordionItem title="Health Checks">
    ```bash
    # Health check script
    #!/bin/bash
    
    # API health check
    if ! curl -f http://localhost:8000/health; then
      echo "API health check failed"
      exit 1
    fi
    
    # Database connectivity
    if ! pg_isready -h postgres -U agentarea; then
      echo "Database connectivity check failed"
      exit 1
    fi
    
    # Redis connectivity
    if ! redis-cli -h redis ping; then
      echo "Redis connectivity check failed"
      exit 1
    fi
    
    echo "All health checks passed"
    ```
  </AccordionItem>
</Accordion>

### Scaling Considerations

<CardGroup cols={2}>
  <Card title="Horizontal Scaling" icon="arrow-right">
    - Add more API server replicas
    - Use load balancer for distribution
    - Implement sticky sessions if needed
    - Scale database read replicas
  </Card>
  
  <Card title="Vertical Scaling" icon="arrow-up">
    - Increase CPU and memory limits
    - Optimize database configuration
    - Tune connection pools
    - Monitor resource utilization
  </Card>
</CardGroup>

---

<Note>
For production deployments, always follow security best practices, implement proper monitoring, and have a disaster recovery plan in place. Consider consulting with our enterprise team for large-scale deployments.
</Note>
## CI/CD container publishing

Our GitHub Actions build and push all Docker images in the monorepo.

- On pushes to `main`, all images are published to Docker Hub with tags:
  - `dev`
  - `commit-<short-sha>`
- Release workflow (`Release Images`) builds all images and tags them with:
  - the provided release version (for example, `v1.2.3`)
  - `latest`
- Helm charts in `charts/*/Chart.yaml` are automatically bumped to the release version via the release workflow and a PR is opened.

Images are published under `agentarea/agentarea-<component>` on Docker Hub for components:
`agentarea-api`, `agentarea-worker`, `agentarea-frontend`, `agentarea-bootstrap`, `agentarea-mcp-manager`.

Authentication for publishing uses repository secrets:
- `DOCKERHUB_USERNAME`
- `DOCKERHUB_PASSWORD`