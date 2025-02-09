```markdown:README.md
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

Start the service:
```bash
poetry run uvicorn src.app.main:app --reload
```

The API will be available at `http://localhost:8000`

## API Endpoints

- `POST /agents/` - Upload a new agent
- `GET /agents/` - List all agents
- `GET /agents/{agent_id}` - Get specific agent details

## File Structure

Files are stored in S3 with the following structure:
```
bucket/
  ├── agents/
  │   └── {agent_id}/
  │       └── agent_file
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
```
