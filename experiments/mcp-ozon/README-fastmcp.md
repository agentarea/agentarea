# REST-to-MCP with FastMCP

This tool creates an MCP server from any provided REST OpenAPI URL using the FastMCP library. The tool generates MCP tools for each endpoint in the OpenAPI specification.

## Features

- Convert REST APIs to MCP servers automatically
- Supports parameter mapping from OpenAPI to MCP
- Dynamic generation of tool functions
- Web transport support via FastMCP

## Installation

Make sure you have the required dependencies:

```bash
pip install fastmcp>=2.0.0 httpx python-dotenv
```

## Usage

The tool supports two modes:

### 1. Generate Mode

Generate MCP tool definitions from an OpenAPI specification:

```bash
python rest-to-mcp-fastmcp.py generate --url https://api.example.com/openapi.json --output mcp_tools.json
```

This will fetch the OpenAPI specification, generate tool definitions, and save them to a file.

### 2. Server Mode

Run an MCP server using previously generated tool definitions:

```bash
python rest-to-mcp-fastmcp.py server --tools mcp_tools.json
```

This will start an MCP server on the default host (`127.0.0.1`) and port (`3000`).

### Optional Parameters

- `--host`: Specify the host to bind the server to (default: `127.0.0.1`)
- `--port`: Specify the port to bind the server to (default: `3000`)

Example:

```bash
python rest-to-mcp-fastmcp.py server --tools mcp_tools.json --host 0.0.0.0 --port 8000
```

## How It Works

1. The tool fetches an OpenAPI specification from a URL
2. It converts each endpoint in the specification to an MCP tool definition
3. In server mode, it creates a FastMCP server and dynamically registers each tool
4. When a tool is called, it proxies the request to the original REST API

## Advantages of FastMCP vs Standard MCP

- Simpler API with decorator syntax
- Built-in support for different transports (Web, Claude Desktop, etc.)
- Better parameter handling and type checking
- More Pythonic interface
- Automatic API documentation
- Can be mounted within other FastMCP apps 