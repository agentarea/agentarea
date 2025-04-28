#!/usr/bin/env python3
"""
REST-to-MCP: A tool that creates an MCP server from any provided REST OpenAPI URL.
This tool fetches an OpenAPI specification and dynamically generates MCP tools for each endpoint.
It supports two modes:
1. Generate mode: Generates MCP tool definitions from an OpenAPI spec and saves them to a file
2. Server mode: Runs an MCP server using previously generated tool definitions
"""

import argparse
import asyncio
import json
import os
import sys
import logging
from typing import Dict, Any, List, Optional, Callable, Awaitable

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel
from fastmcp import FastMCP

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("rest-to-mcp")

# Load environment variables
load_dotenv()

class ToolDefinition(BaseModel):
    """Model for storing tool definitions."""
    name: str
    description: str
    parameters: List[Dict[str, Any]]
    path: str
    method: str
    openapi_params: List[Dict[str, Any]]

async def fetch_openapi_spec(url: str) -> Dict[str, Any]:
    """Fetch OpenAPI specification from a URL."""
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()

def parameter_to_mcp_type(param: Dict[str, Any]) -> str:
    """Convert OpenAPI parameter type to FastMCP parameter type."""
    schema = param.get("schema", {})
    param_type = schema.get("type", "string")
    
    if param_type == "string":
        return "string"
    elif param_type == "integer":
        return "integer"
    elif param_type == "number":
        return "float"
    elif param_type == "boolean":
        return "boolean"
    elif param_type == "array":
        return "array"
    elif param_type == "object":
        return "object"
    else:
        return "string"

def generate_tool_definitions(openapi: Dict[str, Any]) -> List[ToolDefinition]:
    """Generate MCP tool definitions from OpenAPI specification."""
    tool_definitions = []
    paths = openapi.get("paths", {})
    
    for path, methods in paths.items():
        for method, details in methods.items():
            if method.lower() not in ["get", "post", "put", "delete", "patch"]:
                continue
                
            operation_id = details.get("operationId")
            if not operation_id:
                # Generate an operation ID if none exists
                operation_id = f"{method}_{path.replace('/', '_').replace('{', '').replace('}', '')}"
            
            summary = details.get("summary", "")
            description = details.get("description", summary)
            
            # Extract parameters
            parameters = []
            openapi_params = details.get("parameters", [])
            for param in openapi_params:
                param_name = param.get("name", "")
                param_desc = param.get("description", "")
                param_required = param.get("required", False)
                param_type = parameter_to_mcp_type(param)
                
                parameters.append({
                    "name": param_name,
                    "description": param_desc,
                    "type": param_type,
                    "required": param_required
                })
            
            # Add body parameter if it exists
            if "requestBody" in details:
                content = details["requestBody"].get("content", {})
                if "application/json" in content:
                    parameters.append({
                        "name": "body",
                        "description": "Request body",
                        "type": "object",
                        "required": details["requestBody"].get("required", False)
                    })
            
            # Create tool definition
            tool_def = ToolDefinition(
                name=operation_id,
                description=description,
                parameters=parameters,
                path=path,
                method=method,
                openapi_params=openapi_params
            )
            
            tool_definitions.append(tool_def)
    
    return tool_definitions

async def generate_mcp_tools(openapi_url: str, output_file: str):
    """Generate MCP tool definitions from OpenAPI spec and save to file."""
    try:
        # Fetch OpenAPI spec
        logger.info(f"Fetching OpenAPI specification from {openapi_url}...")
        openapi = await fetch_openapi_spec(openapi_url)
        
        # Extract server URL
        server_url = openapi.get("servers", [{}])[0].get("url", "")
        
        # Ensure server URL has a protocol
        if server_url and not server_url.startswith(('http://', 'https://')):
            server_url = f"https://{server_url}"
        
        # Generate tool definitions
        logger.info("Generating MCP tool definitions from OpenAPI specification...")
        tool_definitions = generate_tool_definitions(openapi)
        logger.info(f"Generated {len(tool_definitions)} tool definitions from OpenAPI specification")
        
        # Save to file
        with open(output_file, 'w') as f:
            json.dump({
                "server_url": server_url,
                "tools": [tool_def.dict() for tool_def in tool_definitions]
            }, f, indent=2)
        
        logger.info(f"Tool definitions saved to {output_file}")
        
    except Exception as e:
        logger.error(f"Error generating MCP tools: {e}")
        sys.exit(1)

def create_tool_function(path: str, method: str, openapi_params: List[Dict[str, Any]], server_url: str) -> Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]:
    """Factory function to create a tool function with the correct closure."""
    async def tool_func(input_data: Dict[str, Any]) -> Dict[str, Any]:
        headers = input_data.get("headers", {})
        body = input_data.get("body", None)
        query_params = {}
        path_params = {}
        
        # Separate path and query parameters
        for param in openapi_params:
            param_name = param.get("name", "")
            if param.get("in") == "path" and param_name in input_data:
                path_params[param_name] = input_data[param_name]
            elif param.get("in") == "query" and param_name in input_data:
                query_params[param_name] = input_data[param_name]
        
        # Format path with path parameters
        formatted_path = path
        for key, value in path_params.items():
            formatted_path = formatted_path.replace(f"{{{key}}}", str(value))
        
        url = f"{server_url}{formatted_path}" if server_url else formatted_path
        
        # Ensure URL has a protocol
        if url and not url.startswith(('http://', 'https://')):
            url = f"https://{url}"
        
        logger.info(f"Making request to: {url}")
        
        async with httpx.AsyncClient() as client:
            try:
                req = client.build_request(
                    method.upper(), 
                    url, 
                    headers=headers, 
                    json=body, 
                    params=query_params
                )
                logger.debug(f"Request details: method={method.upper()}, params={query_params}")
                res = await client.send(req)
                logger.info(f"Response status: {res.status_code}")
                
                # Try to parse JSON response
                try:
                    response_body = res.json()
                except:
                    response_body = res.text
                    
                return {
                    "status_code": res.status_code,
                    "headers": dict(res.headers),
                    "body": response_body
                }
            except Exception as e:
                logger.error(f"Error making request to {url}: {str(e)}")
                return {"error": str(e)}
    
    return tool_func

def create_mcp_server(tools_file: str) -> FastMCP:
    """Create an MCP server using tool definitions from a file."""
    logger.info(f"Preparing to create MCP server...")
    # Initialize FastMCP app
    mcp = FastMCP("REST-to-MCP Server", description="MCP server generated from OpenAPI specification")
    
    logger.info(f"Loading tool definitions from {tools_file}")
    with open(tools_file, 'r') as f:
        data = json.load(f)
    
    server_url = data.get("server_url", "")
    
    # Ensure server URL has a protocol
    if server_url and not server_url.startswith(('http://', 'https://')):
        server_url = f"https://{server_url}"
    
    logger.info(f"Server URL: {server_url}")
    
    tool_definitions = data.get("tools", [])
    logger.info(f"Found {len(tool_definitions)} tool definitions")
    
    # Dictionary to store generated functions
    tool_functions = {}
    
    # Create tool functions first to maintain proper scoping
    for tool_def in tool_definitions:
        tool_name = tool_def.get("name", "")
        path = tool_def.get("path", "")
        method = tool_def.get("method", "get")
        openapi_params = tool_def.get("openapi_params", [])
        
        logger.debug(f"Creating function for tool: {tool_name}, path: {path}, method: {method}")
        # Create the tool function with proper closure
        tool_functions[tool_name] = create_tool_function(path, method, openapi_params, server_url)
    
    # Now register each tool with FastMCP
    logger.info("Registering tools with FastMCP")
    for tool_def in tool_definitions:
        tool_name = tool_def.get("name", "")
        description = tool_def.get("description", "")
        
        # Extract parameters for annotation
        tool_params = {}
        for param in tool_def.get("parameters", []):
            param_name = param.get("name", "")
            tool_params[param_name] = {
                "type": param.get("type", "string"),
                "description": param.get("description", ""),
                "required": param.get("required", False)
            }
        
        # Get the corresponding function
        func = tool_functions[tool_name]
        
        # Register the tool with FastMCP
        logger.debug(f"Registering tool: {tool_name}")
        mcp.tool(name=tool_name, description=description)(func)
    
    logger.info("All tools registered successfully")
    
    # Add a simple default tool to check server status
    @mcp.tool()
    def server_info() -> Dict[str, Any]:
        """Get information about this REST-to-MCP server."""
        return {
            "name": "REST-to-MCP Server",
            "description": "MCP server generated from OpenAPI specification",
            "tools_count": len(tool_definitions),
            "server_url": server_url
        }
    
    return mcp

def run_mcp_server_sync(tools_file: str, host: str = "127.0.0.1", port: int = 3000):
    """Synchronous wrapper to run the MCP server."""
    try:
        logger.info(f"Starting REST-to-MCP server with tools from {tools_file}")
        # Create MCP server
        mcp = create_mcp_server(tools_file)
        
        # Start server
        logger.info(f"Starting MCP server at http://{host}:{port}")
        
        # Run with the web transport
        logger.info("Server ready to accept connections")
        mcp.run(transport="sse", host=host, port=port)
        
    except Exception as e:
        logger.error(f"Error running MCP server: {e}")
        sys.exit(1)

def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(description="Create an MCP server from a REST OpenAPI URL")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Generate command
    generate_parser = subparsers.add_parser("generate", help="Generate MCP tool definitions from OpenAPI spec")
    generate_parser.add_argument("--url", required=True, help="URL to the OpenAPI specification")
    generate_parser.add_argument("--output", default="mcp_tools.json", help="Output file for tool definitions")
    
    # Server command
    server_parser = subparsers.add_parser("server", help="Run MCP server using generated tool definitions")
    server_parser.add_argument("--tools", required=True, help="File containing tool definitions")
    server_parser.add_argument("--host", default="127.0.0.1", help="Host to bind the server to")
    server_parser.add_argument("--port", type=int, default=3000, help="Port to bind the server to")
    
    # Add debugging flag
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    # Set debug level if requested
    if hasattr(args, 'debug') and args.debug:
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")
    
    logger.info(f"Running command: {args.command}")
    
    if args.command == "generate":
        logger.info(f"Generating MCP tools from OpenAPI spec at {args.url}")
        asyncio.run(generate_mcp_tools(args.url, args.output))
    elif args.command == "server":
        logger.info(f"Starting server with tools from {args.tools}")
        # For server mode, we don't need to use asyncio.run since FastMCP.run is blocking
        run_mcp_server_sync(args.tools, args.host, args.port)
    else:
        parser.print_help()

if __name__ == "__main__":
    logger.info("REST-to-MCP starting up")
    main() 