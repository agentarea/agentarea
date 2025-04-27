# MCP Server Setup

## Overview
This repository contains the configuration for setting up an MCP (Model Context Protocol) server that can be run from Docker or command line. The setup provides a unified access point for other containers via mcp-host.

## Prerequisites
- Docker and Docker Compose installed
- Basic understanding of Docker networking
- Access to the required API keys for services you want to configure

## Installation
1. Clone this repository
2. Navigate to the mcp directory
3. Run:
   ```bash
   docker-compose up -d
   ```

## Configuration

## Adding a New MCP Server
### CLI-based MCP (like Trello)
Edit the `mcp-hub-settings.json` file to configure your MCP servers.
```json
{
  "mcpServers": {
    "trello": {
      "command": "npx",
      "args": ["-y", "@delorenj/mcp-server-trello"],
      "env": {
        "TRELLO_API_KEY": "your-trello-api-key",
        "TRELLO_BOARD_ID": "your-trello-board-id",
        "TRELLO_TOKEN": "your-trello-token"
      }
    }
  }
}
```

### Docker-based MCP (like mcp-everything)
1. Add service to docker-compose.yaml:
```yaml
mcp-custom-service:
  image: your-mcp-image
  restart: unless-stopped
```

2. Create configuration file in servers directory:
```nginx
# servers/custom-service.conf
location ~ ^/mcp-custom-service {
    rewrite ^/mcp-custom-service/?(.*)$ /$1 break;
    proxy_pass http://mcp-custom-service:9876;

    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 86400;

    proxy_set_header Connection '';
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

## Services
The docker-compose file defines the following services:
- `mcp-host`: Nginx proxy for MCP servers. Services will be published on /<service>/sse endpoint
- `mcp-everything`: MCP everything server example
- `mcp-hub`: MCP hub service for wrapping stdio mcp servers with sse transport

## Check that everything works as expected
1. Connect to mcp-hub endpoint:
```
curl http://localhost:8080/mcp-hub/sse
```

It should respond with:
```
event: endpoint
data: /messages?sessionId=e0581acd-f496-4455-ab12-8f6e3c9ad17d
```

Now you can use this session to list tools available:
```
curl -X POST "http://localhost:8080/mcp-hub/messages?sessionId=e0581acd-f496-4455-ab12-8f6e3c9ad17d" -H "Content-Type: application/json" -d '{ "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": { } }'
```

Example output (formatted):
```
{
  "result": {
    "tools": [
      ...
      {
        "name": "browser_take_screenshot",
        "description": "Take a screenshot of the current page. You can't perform actions based on the screenshot, use browser_snapshot for actions.",
        "inputSchema": {
          "type": "object",
          "properties": {
            "raw": {
              "type": "boolean",
              "description": "Whether to return without compression (in PNG format). Default is false, which returns a JPEG image."
            },
            "element": {
              "type": "string",
              "description": "Human-readable element description used to obtain permission to screenshot the element. If not provided, the screenshot will be taken of viewport. If element is provided, ref must be provided too."
            },
            "ref": {
              "type": "string",
              "description": "Exact target element reference from the page snapshot. If not provided, the screenshot will be taken of viewport. If ref is provided, element must be provided too."
            }
          },
          "additionalProperties": false,
          "$schema": "http://json-schema.org/draft-07/schema#"
        }
      },
      ...
      {
        "name": "add_list_to_board",
        "description": "Add a new list to the board",
        "inputSchema": {
          "type": "object",
          "properties": {
            "name": {
              "type": "string",
              "description": "Name of the new list"
            }
          },
          "required": [
            "name"
          ]
        }
      },
      ...
    ]
  },
  "jsonrpc": "2.0",
  "id": 1
}
```