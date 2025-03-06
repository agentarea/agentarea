import os
import sys
import json
import asyncio
from typing import List, Dict, Any, Optional

# Configure logging
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# MCP SDK imports
try:
    from modelcontextprotocol.client import Client as MCPClient
    from modelcontextprotocol.server import Server as MCPServer
    from modelcontextprotocol.transport.stdio import StdioServerTransport, StdioClientTransport
except ImportError:
    logger.error("Model Context Protocol SDK not found. Install with: pip install modelcontextprotocol")
    sys.exit(1)

class CustomSource:
    """Represents a custom data source that can be exposed via MCP."""
    
    def __init__(self, source_id: str, name: str, source_type: str, connection_details: Dict[str, Any]):
        self.id = source_id
        self.name = name
        self.type = source_type  # "database", "file", "api", etc.
        self.connection_details = connection_details
        self.status = "disconnected"
        self.data = {}  # Cache for data
    
    async def connect(self) -> bool:
        """Connect to the data source."""
        logger.info(f"Connecting to source: {self.name} ({self.id})")
        # Implement connection logic based on source type
        if self.type == "database":
            # Database connection logic
            self.status = "connected"
            return True
        elif self.type == "file":
            # File system connection logic
            try:
                # Simulate reading from a file
                self.data = {"transactions": [
                    {"id": "txn_001", "amount": 100.00, "customer_id": "cus_001", "date": "2023-01-15"},
                    {"id": "txn_002", "amount": 75.50, "customer_id": "cus_002", "date": "2023-01-16"},
                    {"id": "txn_003", "amount": 200.00, "customer_id": "cus_001", "date": "2023-01-20"}
                ]}
                self.status = "connected"
                return True
            except Exception as e:
                logger.error(f"Failed to connect to file source: {str(e)}")
                return False
        elif self.type == "api":
            # API connection logic
            self.status = "connected"
            return True
        
        return False
    
    async def fetch_data(self, query: Optional[str] = None) -> Dict[str, Any]:
        """Fetch data from the source."""
        if self.status != "connected":
            await self.connect()
        
        logger.info(f"Fetching data from source: {self.name}")
        return self.data or {"source_id": self.id, "data": "Sample data"}

class CustomMCPServer:
    """MCP server implementation for custom data sources."""
    
    def __init__(self, server_id: str, name: str):
        self.id = server_id
        self.name = name
        self.sources: List[CustomSource] = []
        self.server = MCPServer({
            "name": name,
            "version": "1.0.0"
        }, {
            "capabilities": {
                "resources": {},
                "tools": {}
            }
        })
    
    def add_source(self, source: CustomSource) -> None:
        """Add a data source to the server."""
        self.sources.append(source)
        logger.info(f"Added source {source.name} to MCP server {self.name}")
    
    async def initialize(self) -> None:
        """Initialize the MCP server with handlers."""
        # Connect all sources
        for source in self.sources:
            await source.connect()
        
        # Set up resource handlers
        self.server.set_request_handler("ListResourcesRequest", self._handle_list_resources)
        self.server.set_request_handler("ReadResourceRequest", self._handle_read_resource)
        
        # Set up tool handlers
        self.server.set_request_handler("ListToolsRequest", self._handle_list_tools)
        self.server.set_request_handler("ExecuteToolRequest", self._handle_execute_tool)
        
        logger.info(f"Initialized MCP server: {self.name}")
    
    async def _handle_list_resources(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle ListResourcesRequest."""
        resources = []
        for source in self.sources:
            resources.append({
                "uri": f"mcp://{self.id}/{source.id}",
                "name": source.name,
                "mimeType": "application/json"
            })
        
        return {"resources": resources}
    
    async def _handle_read_resource(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle ReadResourceRequest."""
        uri = request.get("uri", "")
        # Parse URI to extract source ID
        parts = uri.split("/")
        if len(parts) >= 3:
            source_id = parts[2]
            for source in self.sources:
                if source.id == source_id:
                    data = await source.fetch_data()
                    return {
                        "content": json.dumps(data),
                        "mimeType": "application/json"
                    }
        
        return {"error": "Resource not found"}
    
    async def _handle_list_tools(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle ListToolsRequest."""
        tools = [
            {
                "name": "search_transactions",
                "description": "Search for transactions based on criteria",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "string"},
                        "min_amount": {"type": "number"},
                        "max_amount": {"type": "number"},
                        "date_from": {"type": "string"},
                        "date_to": {"type": "string"}
                    }
                }
            },
            {
                "name": "calculate_metrics",
                "description": "Calculate metrics from transaction data",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "metric": {"type": "string", "enum": ["total", "average", "count"]},
                        "filter": {"type": "object"}
                    },
                    "required": ["metric"]
                }
            }
        ]
        
        return {"tools": tools}
    
    async def _handle_execute_tool(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle ExecuteToolRequest."""
        tool_name = request.get("name", "")
        args = request.get("args", {})
        
        if tool_name == "search_transactions":
            return await self._search_transactions(args)
        elif tool_name == "calculate_metrics":
            return await self._calculate_metrics(args)
        
        return {"error": f"Unknown tool: {tool_name}"}
    
    async def _search_transactions(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Search transactions based on criteria."""
        # Find file source with transactions
        for source in self.sources:
            if source.type == "file":
                data = await source.fetch_data()
                transactions = data.get("transactions", [])
                
                # Apply filters
                filtered = transactions
                if "customer_id" in args:
                    filtered = [t for t in filtered if t.get("customer_id") == args["customer_id"]]
                if "min_amount" in args:
                    filtered = [t for t in filtered if t.get("amount", 0) >= args["min_amount"]]
                if "max_amount" in args:
                    filtered = [t for t in filtered if t.get("amount", 0) <= args["max_amount"]]
                
                return {"results": filtered}
        
        return {"results": []}
    
    async def _calculate_metrics(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate metrics from transaction data."""
        metric = args.get("metric", "")
        
        # Find file source with transactions
        for source in self.sources:
            if source.type == "file":
                data = await source.fetch_data()
                transactions = data.get("transactions", [])
                
                if metric == "total":
                    total = sum(t.get("amount", 0) for t in transactions)
                    return {"result": total}
                elif metric == "average":
                    if not transactions:
                        return {"result": 0}
                    avg = sum(t.get("amount", 0) for t in transactions) / len(transactions)
                    return {"result": avg}
                elif metric == "count":
                    return {"result": len(transactions)}
        
        return {"error": f"Could not calculate metric: {metric}"}
    
    async def start(self) -> None:
        """Start the MCP server."""
        await self.initialize()
        
        # Use stdio transport for local process communication
        transport = StdioServerTransport()
        await self.server.connect(transport)
        
        logger.info(f"MCP server started: {self.name}")

class MCPExperiment:
    """Experiment to test MCP integration with custom sources and Stripe."""
    
    def __init__(self):
        self.custom_server = None
        self.stripe_client = None
    
    async def setup_custom_server(self) -> None:
        """Set up custom MCP server with data sources."""
        # Create custom sources
        db_source = CustomSource(
            source_id="db-001",
            name="Customer Database",
            source_type="database",
            connection_details={
                "host": "localhost",
                "port": 5432,
                "username": "example",
                "password": "example",
                "database": "example"
            }
        )
        
        file_source = CustomSource(
            source_id="file-001",
            name="Transaction Logs",
            source_type="file",
            connection_details={
                "path": "/data/transactions/",
                "format": "json"
            }
        )
        
        # Create and configure MCP server
        self.custom_server = CustomMCPServer(server_id="custom-001", name="Custom Data Server")
        self.custom_server.add_source(db_source)
        self.custom_server.add_source(file_source)
        
        # Start server in background
        asyncio.create_task(self.custom_server.start())
        logger.info("Custom MCP server setup complete")
    
    async def setup_stripe_client(self) -> None:
        """Set up MCP client to connect to Stripe's MCP server."""
        # In a real implementation, you would use Stripe's MCP server details
        # For this example, we'll simulate the connection
        
        self.stripe_client = MCPClient({
            "name": "Stripe MCP Client",
            "version": "1.0.0"
        })
        
        # In a real implementation, you would connect to Stripe's MCP server
        # For now, we'll just log the intent
        logger.info("Stripe MCP client setup (simulated)")
        
        # Note: In a real implementation, you would use something like:
        # transport = HttpClientTransport("https://api.stripe.com/v1/mcp")
        # await self.stripe_client.connect(transport)
    
    async def run_experiment(self) -> None:
        """Run the MCP experiment."""
        logger.info("Starting MCP integration experiment")
        
        # Set up components
        await self.setup_custom_server()
        await self.setup_stripe_client()
        
        # Simulate interactions with our custom MCP server
        logger.info("Simulating MCP interactions:")
        
        # 1. List available resources
        logger.info("1. Listing resources from custom server")
        # In a real implementation:
        # resources = await self.custom_client.list_resources()
        # logger.info(f"Available resources: {resources}")
        
        # 2. Execute a tool
        logger.info("2. Executing 'search_transactions' tool")
        # In a real implementation:
        # result = await self.custom_client.execute_tool(
        #     "search_transactions", 
        #     {"customer_id": "cus_001"}
        # )
        # logger.info(f"Search results: {result}")
        
        # 3. Calculate metrics
        logger.info("3. Executing 'calculate_metrics' tool")
        # In a real implementation:
        # result = await self.custom_client.execute_tool(
        #     "calculate_metrics", 
        #     {"metric": "total"}
        # )
        # logger.info(f"Total amount: {result}")
        
        # 4. Simulate integration with Stripe MCP
        logger.info("4. Simulating Stripe MCP integration")
        logger.info("   This would involve connecting to Stripe's MCP server")
        logger.info("   and using their tools for payment processing, etc.")
        
        logger.info("MCP integration experiment completed")
        logger.info("In a real implementation, you would:")
        logger.info("1. Connect to Stripe's MCP server using their provided credentials")
        logger.info("2. Use Stripe's MCP tools for payment processing, customer management, etc.")
        logger.info("3. Combine data from your custom sources with Stripe's data")

async def main():
    """Main entry point for the experiment."""
    experiment = MCPExperiment()
    await experiment.run_experiment()

if __name__ == "__main__":
    asyncio.run(main())

