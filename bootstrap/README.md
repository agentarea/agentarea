# AgentArea Bootstrap Module

This module handles the initial setup and configuration of the AgentArea platform, including:

1. **MinIO Setup** - Creates necessary S3-compatible storage buckets
2. **Infisical Setup** - Creates Infisical database and configures secrets management system
3. **LLM Providers** - Populates the database with supported LLM providers and models

## Key Changes

- **Shared PostgreSQL Instance**: Infisical now uses the same PostgreSQL instance as the main application, but with a separate `infisical` database
- **Migration Dependencies**: Bootstrap now runs only after database migrations are completed
- **Automatic Database Creation**: The bootstrap process automatically creates the `infisical` database if it doesn't exist

## Prerequisites

- Docker and Docker Compose
- PostgreSQL database (configured in docker-compose)
- MinIO instance (configured in docker-compose)
- Infisical instance (configured in docker-compose)

## Environment Variables

The following environment variables are required:

### Database Configuration
```bash
POSTGRES_USER=agentarea_user
POSTGRES_PASSWORD=your_secure_password_here
POSTGRES_DB=agentarea
POSTGRES_HOST=db
POSTGRES_PORT=5432
DATABASE_URL=postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}
```

**Note**: The bootstrap process will automatically create an `infisical` database in the same PostgreSQL instance.

### MinIO Configuration
```bash
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin123
MINIO_ENDPOINT=http://minio:9000
DOCUMENTS_BUCKET=documents
```

### Bootstrap Configuration
```bash
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=your-secure-admin-password
ORGANIZATION_NAME=AgentArea
```

### Infisical Configuration
```bash
INFISICAL_URL=http://infisical:8080
```

## Usage

### With Docker Compose (Recommended)

The bootstrap module is automatically run as part of the docker-compose setup:

```bash
docker compose -f docker-compose.dev.yaml up -d
```

The bootstrap service will:
1. Wait for database and MinIO to be healthy
2. Wait for database migrations to complete
3. Set up MinIO buckets
4. Create Infisical database (if it doesn't exist)
5. Configure Infisical
6. Populate LLM providers from the YAML configuration

### Manual Execution

If you need to run the bootstrap manually:

```bash
cd bootstrap
python main.py
```

## Configuration Files

### `scripts/providers.yaml`
Contains the configuration for supported LLM providers and their models. This file defines:
- Provider names and descriptions
- Available models for each provider
- Context window sizes
- Pricing information (for reference)
- **Unique UUIDs** for each provider to prevent duplicates during bootstrap

#### LLM Provider UUIDs

Each provider in the YAML configuration now includes a unique `id` field with a UUID. This ensures:
- Consistent provider IDs across multiple bootstrap runs
- Prevention of duplicate provider entries
- Proper referential integrity with models

Example provider configuration:
```yaml
openai:
  id: "550e8400-e29b-41d4-a716-446655440001"
  name: "OpenAI"
  models:
    - name: "gpt-3.5-turbo"
      description: "GPT-3.5 Turbo model for general purpose tasks"
      # ... other model properties
```

#### Adding New Providers

When adding new providers to the YAML file:

1. **Generate a UUID** using the provided utility script:
   ```bash
   cd bootstrap
   python scripts/generate_provider_uuid.py [provider_name]
   ```

2. **Add the provider** to `scripts/providers.yaml` with the generated UUID:
   ```yaml
   new_provider:
     id: "generated-uuid-here"
     name: "New Provider Name"
     models: []
   ```

3. **Test the configuration** by running the bootstrap process

### `code/` Directory
Contains the implementation modules:
- `populate_llm_providers.py` - Database population logic with UUID-based upserts
- `minio_setup.py` - MinIO bucket creation and configuration
- `infisical_setup.py` - Infisical bootstrap and setup

### `scripts/` Directory
Contains utility scripts:
- `generate_provider_uuid.py` - Utility to generate UUIDs for new providers

## Dependencies

The module uses the following Python packages:
- `requests` - HTTP client for API calls
- `sqlalchemy` - Database ORM
- `psycopg2-binary` - PostgreSQL driver
- `pyyaml` - YAML file parsing

## Troubleshooting

### Common Issues

1. **Database Connection Failed**
   - Ensure PostgreSQL is running and accessible
   - Check DATABASE_URL environment variable
   - Verify database credentials

2. **MinIO Setup Failed**
   - Ensure MinIO service is healthy
   - Check MinIO credentials and endpoint
   - Verify MinIO client (`mc`) is installed

3. **Infisical Setup Failed**
   - Ensure Infisical service is running
   - Check Infisical URL and network connectivity
   - Verify admin credentials

### Logs

The bootstrap process provides detailed logging. Check the container logs:

```bash
docker compose -f docker-compose.dev.yaml logs bootstrap
```

## Testing

To test the database setup:

```bash
# Run the database connection test
docker compose -f docker-compose.dev.yaml exec bootstrap python test_db_setup.py
```

This will verify that both the main application database and the Infisical database are accessible.

## Development

To modify the bootstrap process:

1. Edit the relevant files in the `code/` directory
2. Update `scripts/providers.yaml` to add/modify LLM providers
3. Rebuild the Docker image:
   ```bash
   docker compose -f docker-compose.dev.yaml build bootstrap
   ```
