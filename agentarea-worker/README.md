# AI Agent Service

A service for managing AI agents with S3 storage.

## Setup

1. Install dependencies:
```bash
poetry install
```

2. Configure S3 access:

Create a `.env` file in the root directory with the following variables:
```bash
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_REGION=your_region
S3_BUCKET_NAME=your_bucket_name
```

3. S3 Bucket Setup:
- Create an S3 bucket in your AWS account
- Ensure the bucket has the following structure:
```
bucket/
  ├── agents/     # Stores agent files
  └── metadata/   # Stores agent metadata
```
- Configure CORS if needed:
```json
{
    "CORSRules": [
        {
            "AllowedHeaders": ["*"],
            "AllowedMethods": ["GET", "PUT", "POST"],
            "AllowedOrigins": ["*"],
            "ExposeHeaders": []
        }
    ]
}
```

4. Required IAM Permissions:
The AWS credentials should have the following permissions on the S3 bucket:
- s3:PutObject
- s3:GetObject
- s3:ListBucket

## Running the Service

### Using the CLI

Start the service with default settings:
```bash
poetry run python -m src.cli serve
```

The service supports various configuration options:
```bash
poetry run python -m src.cli serve --help
```

Available options:
- `--host`: Host to bind the server to (default: 0.0.0.0)
- `--port`: Port to bind the server to (default: 8000 or PORT env var)
- `--reload/--no-reload`: Enable/disable auto-reload on code changes (default: enabled)
- `--log-level`: Set logging level (options: critical, error, warning, info, debug, trace)
- `--access-log/--no-access-log`: Enable/disable HTTP access logs (default: enabled)
- `--workers`: Number of worker processes (default: 1)
- `--log-config`: Path to custom logging configuration file (YAML format)

Example with custom options:
```bash
poetry run python -m src.cli serve --port=9000 --log-level=debug --workers=4 --no-reload
```

Example with custom logging configuration:
```bash
poetry run python -m src.cli serve --log-config=logging_config.yaml
```

### Using Docker Compose

Start all services:
```bash
docker-compose up
```

You can configure server options via environment variables in your .env file:
- `PORT`: Server port (default: 8000)
- `LOG_LEVEL`: Logging level (default: info)
- `RELOAD`: Enable/disable auto-reload (default: true)
- `WORKERS`: Number of worker processes (default: 1)
- `LOG_CONFIG`: Path to custom logging configuration file

### Custom Logging Configuration

The service follows 12-factor app principles for logging, treating logs as event streams and outputting to stdout/stderr rather than writing to files. A sample configuration file is provided at `logging_config.yaml.example`.

To use custom logging configuration:

1. Copy the example file:
```bash
cp logging_config.yaml.example logging_config.yaml
```

2. Modify the configuration as needed. The default configuration:
   - Outputs all logs to stdout/stderr
   - Formats logs in a readable format
   - Configures different log levels for different components

3. Run the service with the custom configuration:
```bash
poetry run python -m src.cli serve --log-config=logging_config.yaml
```

Or with Docker Compose, set in your .env file:
```
LOG_CONFIG=logging_config.yaml
```

#### Log Collection in Production

In a production environment, logs should be collected from stdout/stderr by the platform's logging infrastructure:

- In Kubernetes: Use a logging agent like Fluentd or Fluent Bit
- In Docker: Use the Docker logging driver
- In cloud platforms: Use the platform's log collection service (e.g., CloudWatch Logs in AWS)

This approach allows for centralized log management without modifying the application.

The API will be available at `http://localhost:8000`

## API Endpoints

- `POST /agents/` - Upload a new agent
- `GET /agents/` - List all agents
- `GET /agents/{agent_id}` - Get specific agent details
- `POST /sources/upload` - Upload a file to the system
- `POST /sources/` - Create a new source
- `GET /sources/` - List all sources
- `GET /sources/{source_id}` - Get a specific source
- `PUT /sources/{source_id}` - Update a source
- `DELETE /sources/{source_id}` - Delete a source

## File Structure

Files are stored in S3 with the following structure:
```
bucket/
  ├── agents/
  │   └── {agent_id}/
  │       └── agent_file
  ├── uploads/
  │   └── {source_id}/
  │       └── {timestamp}{extension}
  └── metadata/
      └── {agent_id}.json
```

## API Request Examples

### Upload Agent
```bash
curl -X POST http://localhost:8000/agents/ \
  -F "agent_file=@/path/to/agent.py" \
  -F "metadata_file=@/path/to/metadata.yaml"
```

Example metadata.yaml:
```yaml
name: "My Agent"
version: "1.0.0"
description: "An example AI agent"
input_format: "text"
output_format: "json"
purpose: "Text processing"
author: "John Doe"
requirements:
  - "tensorflow>=2.0.0"
tags:
  - "nlp"
  - "text-processing"
environment:
  MODEL_PATH: "/models/v1"
license: "MIT"
model_framework: "tensorflow"
system_requirements:
  memory_requirements: "8GB"
  gpu_requirements: true
```

### List Agents
```bash
curl http://localhost:8000/agents/
```

### Get Agent
```bash
curl http://localhost:8000/agents/{agent_id}
```

### Upload File
```bash
curl -X POST http://localhost:8000/sources/upload \
  -F "file=@/path/to/file.csv" \
  -F "file_type=csv" \
  -F "description=My data file" \
  -F "owner=user123"
```
