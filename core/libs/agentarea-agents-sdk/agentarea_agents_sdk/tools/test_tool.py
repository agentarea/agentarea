"""Test tool for comprehensive agent behavior validation."""

from typing import Any

from .base_tool import BaseTool


class TestTool(BaseTool):
    """Test tool that simulates tool execution with configurable responses.

    This tool is designed for testing agent ReAct patterns and can simulate
    various scenarios like data retrieval, calculations, or status checks.
    """

    @property
    def name(self) -> str:
        return "test_tool"

    @property
    def description(self) -> str:
        return (
            "Test tool for agent validation. Can simulate data retrieval, calculations, "
            "or status checks. Returns realistic responses for testing agent behavior."
        )

    def get_schema(self) -> dict[str, Any]:
        """Get the tool parameter schema."""
        return {
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action to perform: 'get_data', 'calculate', 'check_status', 'search'",
                        "enum": ["get_data", "calculate", "check_status", "search"],
                    },
                    "query": {"type": "string", "description": "Query or parameter for the action"},
                },
                "required": ["action"],
            }
        }

    async def execute(self, **kwargs) -> dict[str, Any]:
        """Execute the test tool with realistic responses.

        Args:
            action: The action to perform
            query: Optional query parameter

        Returns:
            Dict containing realistic test results
        """
        action = kwargs.get("action", "get_data")
        query = kwargs.get("query", "")

        # Simulate different types of tool responses
        if action == "get_data":
            return {
                "success": True,
                "result": f"Retrieved data for '{query}': Sample dataset contains 42 records with total size 1.2MB. Last updated: 2024-01-15.",
                "data_count": 42,
                "size_mb": 1.2,
                "tool_name": self.name,
                "error": None,
            }

        elif action == "calculate":
            # Simple calculation simulation
            result = f"Calculation for '{query}': Result is 73.5 (based on input parameters). Confidence: 95%"
            return {
                "success": True,
                "result": result,
                "calculation_result": 73.5,
                "confidence": 0.95,
                "tool_name": self.name,
                "error": None,
            }

        elif action == "check_status":
            return {
                "success": True,
                "result": f"Status check for '{query}': System is operational. CPU: 45%, Memory: 62%, Disk: 78%",
                "status": "operational",
                "cpu_usage": 45,
                "memory_usage": 62,
                "disk_usage": 78,
                "tool_name": self.name,
                "error": None,
            }

        elif action == "search":
            return {
                "success": True,
                "result": f"Search results for '{query}': Found 5 matching items. Top result: 'Advanced Analytics Guide' (relevance: 0.89)",
                "results_count": 5,
                "top_result": "Advanced Analytics Guide",
                "relevance": 0.89,
                "tool_name": self.name,
                "error": None,
            }

        else:
            return {
                "success": False,
                "result": f"Unknown action: {action}",
                "tool_name": self.name,
                "error": f"Unsupported action: {action}",
            }
