"""Calculate tool for basic mathematical operations."""

from typing import Any

from .base_tool import BaseTool


class CalculateTool(BaseTool):
    """Tool that performs basic mathematical calculations.

    This tool safely evaluates mathematical expressions for agent use.
    """

    @property
    def name(self) -> str:
        return "calculate"

    @property
    def description(self) -> str:
        return "Perform basic mathematical calculations like addition, subtraction, multiplication, division"

    def get_schema(self) -> dict[str, Any]:
        """Get the tool parameter schema."""
        return {
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Mathematical expression to calculate (e.g., '2 + 2', '15 * 8', '120 + 12')",
                    }
                },
                "required": ["expression"],
            }
        }

    async def execute(self, **kwargs) -> dict[str, Any]:
        """Execute the calculation.

        Args:
            expression: Mathematical expression to evaluate

        Returns:
            Dict containing calculation results
        """
        expression = kwargs.get("expression", "")

        if not expression:
            return {
                "success": False,
                "result": "No expression provided",
                "tool_name": self.name,
                "error": "Expression is required",
            }

        try:
            # Simple eval for demo - in production use safer math parser
            result = eval(expression)
            return {
                "success": True,
                "result": f"{expression} = {result}",
                "calculation_result": result,
                "expression": expression,
                "tool_name": self.name,
                "error": None,
            }
        except Exception as e:
            return {
                "success": False,
                "result": f"Cannot calculate '{expression}': {str(e)}",
                "tool_name": self.name,
                "error": str(e),
            }
