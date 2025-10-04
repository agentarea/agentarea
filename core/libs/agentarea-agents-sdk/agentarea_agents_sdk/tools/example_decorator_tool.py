"""Example usage of the Toolset approach for creating tools."""

import asyncio
import json
from pathlib import Path

from agentarea_agents_sdk.tools import FileToolset, Toolset, ToolsetAdapter, tool_method


class MathToolset(Toolset):
    """A mathematical calculation tool that supports multiple operations."""

    @tool_method
    async def add(self, a: float, b: float) -> str:
        """Add two numbers together.

        Args:
            a: First number
            b: Second number

        Returns:
            String representation of the result
        """
        result = a + b
        return f"{a} + {b} = {result}"

    @tool_method
    async def subtract(self, a: float, b: float) -> str:
        """Subtract second number from first.

        Args:
            a: Number to subtract from
            b: Number to subtract

        Returns:
            String representation of the result
        """
        result = a - b
        return f"{a} - {b} = {result}"

    @tool_method
    async def multiply(self, a: float, b: float) -> str:
        """Multiply two numbers.

        Args:
            a: First number
            b: Second number

        Returns:
            String representation of the result
        """
        result = a * b
        return f"{a} * {b} = {result}"

    @tool_method
    async def divide(self, a: float, b: float) -> str:
        """Divide first number by second.

        Args:
            a: Dividend
            b: Divisor

        Returns:
            String representation of the result

        Raises:
            ValueError: If b is zero
        """
        if b == 0:
            raise ValueError("Cannot divide by zero")
        result = a / b
        return f"{a} / {b} = {result}"


class DataToolset(Toolset):
    """A simple data retrieval and processing tool."""

    @tool_method
    async def search(self, query: str, limit: int | None = 10) -> str:
        """Search for data matching the query.

        Args:
            query: Search query string
            limit: Maximum number of results to return (default: 10)

        Returns:
            Search results as a formatted string
        """
        # Simulate search results
        results = [
            f"Result {i + 1}: Data matching '{query}'"
            for i in range(min(limit, 5))  # Simulate up to 5 results
        ]
        return f"Found {len(results)} results for '{query}':\n" + "\n".join(results)

    @tool_method
    async def get_details(self, item_id: str) -> str:
        """Get detailed information about a specific item.

        Args:
            item_id: Unique identifier for the item

        Returns:
            Detailed information about the item
        """
        # Simulate item details
        return (
            f"Details for item {item_id}:\n"
            f"- Name: Sample Item {item_id}\n"
            f"- Type: Data Object\n"
            f"- Status: Active\n"
            f"- Created: 2024-01-15\n"
            f"- Size: 1.2 MB"
        )


class SimpleToolset(Toolset):
    """A simple tool with a single method to demonstrate single-method tools."""

    @tool_method
    async def echo(self, message: str, repeat: int | None = 1) -> str:
        """Echo a message, optionally repeating it.

        Args:
            message: The message to echo
            repeat: Number of times to repeat the message (default: 1)

        Returns:
            The echoed message
        """
        return (message + " ") * repeat


async def main():
    """Example usage of different toolsets."""
    print("=== MathToolset Example ===")
    math_toolset = MathToolset()

    # Test math operations
    result = await math_toolset.execute(action="add", a=5, b=3)
    print(f"5 + 3 = {result['result']}")

    result = await math_toolset.execute(action="multiply", a=4, b=7)
    print(f"4 * 7 = {result['result']}")

    print("\n=== DataToolset Example ===")
    data_toolset = DataToolset()

    # Test data operations
    result = await data_toolset.execute(action="search", query="test", limit=5)
    print(f"Search results: {result['result']}")

    result = await data_toolset.execute(action="get_details", item_id="123")
    print(f"Item details: {result['result']}")

    print("\n=== SimpleToolset Example ===")
    simple_toolset = SimpleToolset()

    result = await simple_toolset.execute(action="echo", message="Hello, World!", repeat=1)
    print(f"Echo result: {result['result']}")

    print("\n=== FileToolset Example ===")
    # Create a temporary directory for file operations
    import tempfile

    with tempfile.TemporaryDirectory() as temp_dir:
        file_toolset = FileToolset(base_dir=Path(temp_dir))

        # Save a file
        result = await file_toolset.execute(
            action="save_file", contents="Hello from FileToolset!", file_name="example.txt"
        )
        print(f"Save file result: {result['result']}")

        # Read the file back
        result = await file_toolset.execute(action="read_file", file_name="example.txt")
        print(f"Read file result: {result['result']}")

        # List files
        result = await file_toolset.execute(action="list_files")
        print(f"List files result: {result['result']}")

    print("\n=== ToolsetAdapter Example ===")
    # Show how to use with existing BaseTool interface
    adapter = ToolsetAdapter(math_toolset)
    openai_def = adapter.get_openai_function_definition()
    print(f"OpenAI function definition: {json.dumps(openai_def, indent=2)}")


if __name__ == "__main__":
    asyncio.run(main())
