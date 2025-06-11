#!/usr/bin/env python3
"""
Simple Echo MCP Server for testing AgentArea infrastructure
"""

import os
from datetime import datetime, timezone
from typing import Dict, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


class EchoRequest(BaseModel):
    message: str
    metadata: Dict[str, Any] = {}


class EchoResponse(BaseModel):
    original_message: str
    echo_message: str
    timestamp: str
    service_name: str
    metadata: Dict[str, Any] = {}


app = FastAPI(
    title="Echo MCP Server",
    description="Simple echo service for testing MCP infrastructure",
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

# Get service configuration
SERVICE_NAME = os.getenv("MCP_SERVICE_NAME", "echo")
PORT = int(os.getenv("MCP_PORT", "8000"))


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": SERVICE_NAME,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0"
    }


@app.get("/")
async def root():
    """Root endpoint with service information"""
    return {
        "service": SERVICE_NAME,
        "type": "mcp-echo-server",
        "version": "1.0.0",
        "description": "Simple echo service for testing MCP infrastructure",
        "endpoints": {
            "health": "/health",
            "echo": "/echo",
            "info": "/info"
        }
    }


@app.post("/echo", response_model=EchoResponse)
async def echo_message(request: EchoRequest):
    """Echo the received message"""
    echo_msg = f"Echo: {request.message}"
    
    return EchoResponse(
        original_message=request.message,
        echo_message=echo_msg,
        timestamp=datetime.now(timezone.utc).isoformat(),
        service_name=SERVICE_NAME,
        metadata=request.metadata
    )


@app.get("/echo/{message}")
async def echo_get(message: str):
    """Echo a message via GET request"""
    return {
        "original_message": message,
        "echo_message": f"Echo: {message}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service_name": SERVICE_NAME,
        "method": "GET"
    }


@app.get("/info")
async def service_info():
    """Get detailed service information"""
    return {
        "service_name": SERVICE_NAME,
        "service_type": "mcp-echo-server", 
        "version": "1.0.0",
        "description": "Simple echo service for testing MCP infrastructure",
        "capabilities": [
            "echo",
            "health_check",
            "service_info"
        ],
        "environment": {
            "port": PORT,
            "service_name": SERVICE_NAME
        },
        "uptime": "Running",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.get("/mcp/capabilities")
async def mcp_capabilities():
    """MCP protocol capabilities endpoint"""
    return {
        "protocol_version": "1.0",
        "capabilities": {
            "echo": {
                "description": "Echo messages back to the client",
                "methods": ["POST /echo", "GET /echo/{message}"]
            },
            "health": {
                "description": "Service health check",
                "methods": ["GET /health"]
            },
            "info": {
                "description": "Service information",
                "methods": ["GET /info"]
            }
        },
        "service_metadata": {
            "name": SERVICE_NAME,
            "type": "echo",
            "version": "1.0.0"
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info") 