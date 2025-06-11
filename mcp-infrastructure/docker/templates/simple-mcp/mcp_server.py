#!/usr/bin/env python3
"""
Simple MCP Context7 Server
Provides basic MCP functionality with one method
"""

import os
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


class MCPRequest(BaseModel):
    """Base MCP request"""
    jsonrpc: str = "2.0"
    method: str
    params: Optional[Dict[str, Any]] = None
    id: Optional[str] = None


class MCPResponse(BaseModel):
    """Base MCP response"""
    jsonrpc: str = "2.0"
    id: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None


class MCPError(BaseModel):
    """MCP error response"""
    code: int
    message: str
    data: Optional[Dict[str, Any]] = None


class SimpleData(BaseModel):
    """Simple data model for testing"""
    text: str
    timestamp: str
    server_id: str


# Get server configuration
SERVICE_NAME = os.getenv("MCP_SERVICE_NAME", "simple-mcp")
PORT = int(os.getenv("MCP_PORT", "8000"))
SERVER_ID = f"{SERVICE_NAME}-{uuid.uuid4().hex[:8]}"

app = FastAPI(
    title=f"Simple MCP Server ({SERVER_ID})",
    description="Basic MCP Context7 server for testing",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage for testing
data_store: Dict[str, SimpleData] = {}


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": SERVICE_NAME,
        "server_id": SERVER_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
        "data_count": len(data_store)
    }


@app.get("/")
async def root():
    """Root endpoint with server information"""
    return {
        "service": SERVICE_NAME,
        "server_id": SERVER_ID,
        "type": "mcp-context7-server",
        "version": "1.0.0",
        "description": "Simple MCP Context7 server for testing",
        "methods": ["store_text", "get_text", "list_texts"],
        "endpoints": {
            "health": "/health",
            "mcp": "/mcp",
            "info": "/info"
        }
    }


@app.post("/mcp")
async def mcp_handler(request: MCPRequest):
    """Main MCP JSON-RPC endpoint"""
    try:
        if request.method == "store_text":
            return await handle_store_text(request)
        elif request.method == "get_text":
            return await handle_get_text(request)
        elif request.method == "list_texts":
            return await handle_list_texts(request)
        else:
            return MCPResponse(
                id=request.id,
                error={
                    "code": -32601,
                    "message": f"Method not found: {request.method}",
                    "data": {"available_methods": ["store_text", "get_text", "list_texts"]}
                }
            )
    except Exception as e:
        return MCPResponse(
            id=request.id,
            error={
                "code": -32603,
                "message": "Internal error",
                "data": {"error": str(e)}
            }
        )


async def handle_store_text(request: MCPRequest) -> MCPResponse:
    """Store text data"""
    params = request.params or {}
    text = params.get("text")
    key = params.get("key") or str(uuid.uuid4())
    
    if not text:
        return MCPResponse(
            id=request.id,
            error={
                "code": -32602,
                "message": "Invalid params: 'text' is required"
            }
        )
    
    data = SimpleData(
        text=text,
        timestamp=datetime.now(timezone.utc).isoformat(),
        server_id=SERVER_ID
    )
    
    data_store[key] = data
    
    return MCPResponse(
        id=request.id,
        result={
            "key": key,
            "stored": True,
            "data": data.model_dump(),
            "server_id": SERVER_ID
        }
    )


async def handle_get_text(request: MCPRequest) -> MCPResponse:
    """Get text data by key"""
    params = request.params or {}
    key = params.get("key")
    
    if not key:
        return MCPResponse(
            id=request.id,
            error={
                "code": -32602,
                "message": "Invalid params: 'key' is required"
            }
        )
    
    if key not in data_store:
        return MCPResponse(
            id=request.id,
            error={
                "code": -32600,
                "message": f"Key not found: {key}"
            }
        )
    
    data = data_store[key]
    return MCPResponse(
        id=request.id,
        result={
            "key": key,
            "data": data.model_dump(),
            "server_id": SERVER_ID
        }
    )


async def handle_list_texts(request: MCPRequest) -> MCPResponse:
    """List all stored texts"""
    items = []
    for key, data in data_store.items():
        items.append({
            "key": key,
            "data": data.model_dump()
        })
    
    return MCPResponse(
        id=request.id,
        result={
            "items": items,
            "count": len(items),
            "server_id": SERVER_ID
        }
    )


@app.get("/info")
async def service_info():
    """Get detailed service information"""
    methods_info = [
        {
            "name": "store_text",
            "description": "Store text data with optional key",
            "params": ["text", "key?"]
        },
        {
            "name": "get_text", 
            "description": "Get text data by key",
            "params": ["key"]
        },
        {
            "name": "list_texts",
            "description": "List all stored texts",
            "params": []
        }
    ]
    
    return {
        "service_name": SERVICE_NAME,
        "server_id": SERVER_ID,
        "service_type": "mcp-context7-server",
        "version": "1.0.0",
        "description": "Simple MCP Context7 server for testing",
        "methods": methods_info,
        "data_count": len(data_store),
        "uptime": "Running",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# Test endpoints for easy access
@app.post("/test/store")
async def test_store(text: str, key: Optional[str] = None):
    """Direct test endpoint for storing text"""
    request = MCPRequest(
        method="store_text",
        params={"text": text, "key": key},
        id=str(uuid.uuid4())
    )
    return await mcp_handler(request)


@app.get("/test/get/{key}")
async def test_get(key: str):
    """Direct test endpoint for getting text"""
    request = MCPRequest(
        method="get_text",
        params={"key": key},
        id=str(uuid.uuid4())
    )
    return await mcp_handler(request)


@app.get("/test/list")
async def test_list():
    """Direct test endpoint for listing texts"""
    request = MCPRequest(
        method="list_texts",
        id=str(uuid.uuid4())
    )
    return await mcp_handler(request)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info") 