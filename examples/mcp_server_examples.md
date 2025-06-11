# MCP Server Configuration Examples

This document shows how to properly configure MCP servers using the environment variable schema pattern.

## Key Concepts

1. **MCP Server Definition**: Defines the Docker image and what environment variables it needs (schema only)
2. **MCP Instance**: Provides actual values for those environment variables
3. **Tool Discovery**: Tools are discovered dynamically via MCP protocol, not predefined

## Example 1: Weather MCP Server

### Server Definition (Schema)
```json
{
  "name": "weather-mcp",
  "description": "Weather information MCP server",
  "version": "1.0.0",
  "docker_image_url": "myorg/weather-mcp:latest",
  "env_schema": [
    {
      "name": "API_KEY",
      "type": "string", 
      "required": true,
      "description": "Weather API key for external service"
    },
    {
      "name": "DEFAULT_LOCATION",
      "type": "string",
      "required": false,
      "description": "Default location for weather queries"
    }
  ]
}
```

### Instance Configuration (Actual Values)
```json
{
  "name": "weather-instance-prod",
  "server_id": "weather-mcp",
  "config": {
    "env": {
      "API_KEY": "actual-api-key-here",
      "DEFAULT_LOCATION": "San Francisco"
    }
  }
}
```

### Usage with CLI
```bash
# Test the weather MCP server
python scripts/run_mcp_tests.py \
  --image myorg/weather-mcp:latest \
  --env API_KEY=your_actual_key \
  --env DEFAULT_LOCATION="New York" \
  --name weather-test
```

## Example 2: File System MCP Server

### Server Definition (Schema)
```json
{
  "name": "filesystem-mcp",
  "description": "File system operations MCP server", 
  "version": "1.0.0",
  "docker_image_url": "myorg/filesystem-mcp:latest",
  "env_schema": [
    {
      "name": "ALLOWED_PATHS",
      "type": "string",
      "required": true,
      "description": "Comma-separated list of allowed paths"
    },
    {
      "name": "READ_ONLY",
      "type": "boolean",
      "required": false,
      "description": "Whether to restrict to read-only operations"
    }
  ]
}
```

### Instance Configuration (Actual Values)
```json
{
  "name": "filesystem-instance-dev",
  "server_id": "filesystem-mcp", 
  "config": {
    "env": {
      "ALLOWED_PATHS": "/workspace,/tmp",
      "READ_ONLY": "false"
    }
  }
}
```

### Usage with CLI
```bash
# Test the filesystem MCP server
python scripts/run_mcp_tests.py \
  --image myorg/filesystem-mcp:latest \
  --env ALLOWED_PATHS="/workspace,/home/user/projects" \
  --env READ_ONLY=false \
  --name filesystem-test
```

## Example 3: External MCP Server (URL-based)

For already running MCP servers, you don't need to define schemas:

```bash
# Test an external MCP server
python scripts/run_mcp_tests.py \
  --url http://external-mcp-server:3000 \
  --name external-test
```

## Benefits of This Approach

1. **Security**: Environment variables are not stored in code/configs
2. **Team-friendly**: Each team member provides their own API keys/secrets
3. **Separation of Concerns**: MCP manager handles containers, not tool definitions
4. **Dynamic Discovery**: Tools are discovered at runtime via MCP protocol
5. **Flexible Deployment**: Same server definition can be used with different env values

## Similar to Airbyte Pattern

This follows the same pattern as Airbyte connectors:
- **Specification**: Define what configuration parameters are needed
- **Instance**: Provide actual values for those parameters  
- **Runtime Discovery**: Discover capabilities dynamically 