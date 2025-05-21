#!/bin/bash

# Set default values for environment variables
ADMIN_EMAIL=${ADMIN_EMAIL:-admin@example.com}
ADMIN_PASSWORD=${ADMIN_PASSWORD:-your-secure-password}
ORGANIZATION_NAME=${ORGANIZATION_NAME:-your-org-name}
INFISICAL_URL=${INFISICAL_URL:-http://infisical:8080}

# Set MinIO environment variables
MINIO_ROOT_USER=${MINIO_ROOT_USER:-minioadmin}
MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD:-minioadmin}
MINIO_ENDPOINT=${MINIO_ENDPOINT:-http://minio:9000}

# Configure MinIO client
mc alias set myminio $MINIO_ENDPOINT $MINIO_ROOT_USER $MINIO_ROOT_PASSWORD

# Create bucket if it doesn't exist
if ! mc ls myminio/documents > /dev/null 2>&1; then
  echo "Creating MinIO documents bucket..."
  mc mb myminio/documents
  mc policy set public myminio/documents
  echo "MinIO documents bucket created and set to public."
else
  echo "MinIO documents bucket already exists."
fi

# Make the API call to bootstrap Infisical and capture HTTP status code
status_code=$(curl -s -o /tmp/response.json -w "%{http_code}" -X POST \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\",\"organization\":\"$ORGANIZATION_NAME\"}" \
  $INFISICAL_URL/api/v1/admin/bootstrap)

# Check if the request was successful (HTTP 200)
if [ "$status_code" -eq 200 ]; then
  echo "Successfully bootstrapped Infisical."
  cat /tmp/response.json > /app/data/infisical_config.json
  exit 0
# Check if instance was already setup (HTTP 409 Conflict)
elif [ "$status_code" -eq 400 ]; then
  echo "Infisical instance was already setup."
  exit 0
else
  echo "Failed to bootstrap Infisical. Status code: $status_code"
  cat /tmp/response.json
  exit 1
fi
