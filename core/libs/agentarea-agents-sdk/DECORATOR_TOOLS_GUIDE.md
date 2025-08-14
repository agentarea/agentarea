# Toolset Guide

This guide explains the new decorator-based approach for creating toolsets in the AgentArea SDK. A toolset represents a collection of related tool methods that can be called individually. This approach provides a cleaner, more intuitive way to define tools compared to the traditional `BaseTool` implementation.

## Overview

The new decorator-based approach offers several advantages:

- ✅ **Automatic schema generation** from method signatures and type hints
- ✅ **Less boilerplate code** - no need to manually define schemas
- ✅ **Type safety** through Python type hints
- ✅ **Better organization** - one method per function
- ✅ **Self-documenting** through docstrings
- ✅ **Backward compatible** with existing `BaseTool` interface
- ✅ **Logical grouping** - related functionality can be grouped together in a single toolset

## Quick Start

### 1. Import the Required Components

```python
from agentarea_agents_sdk.tools import Toolset, tool_method
```

### 2. Create a Tool Class

```python
class MathTool(DecoratorBaseTool):
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
    async def multiply(self, a: float, b: float) -> str:
        """Multiply two numbers."""
        result = a * b
        return f"{a} * {b} = {result}"
```

### 3. Use the Tool

```python
# Create and use the tool directly
math_tool = MathTool()
result = await math_tool.execute(action="add", add_a=5, add_b=3)
print(result)  # {'success': True, 'result': '5 + 3 = 8', ...}

# Or integrate with existing ToolExecutor
from agentarea_agents_sdk.tools import ToolExecutor, DecoratorToolAdapter

executor = ToolExecutor()
adapter = DecoratorToolAdapter(math_tool)
executor.register_tool(adapter)
```

## Key Concepts

### Toolset Name and Description

- **Toolset name**: Automatically generated from class name (CamelCase → snake_case, removes "_toolset" suffix)
- **Toolset description**: Taken from the class docstring

```python
class DataProcessorToolset(Toolset):
    """Toolset for processing and analyzing data."""
    # Toolset name will be: "data_processor"
    # Description will be: "Toolset for processing and analyzing data."
```

### Method Decoration

Use the `@tool_method` decorator to mark methods as tool functions. The description is automatically extracted from the method's docstring:

```python
@tool_method
async def my_method(self, param1: str, param2: int = 10) -> str:
    """Custom description for this method.
    
    Method docstring provides additional context."""
    return f"Processed {param1} with value {param2}"
```

The decorator can be used as `@tool_method` or `@tool_method()` - both work the same way.
```

### Type Hints and Schema Generation

The system automatically generates OpenAI function schemas from your type hints:

```python
@tool_method()
async def process_data(
    self,
    query: str,                    # Required string parameter
    limit: Optional[int] = 10,     # Optional integer with default
    include_metadata: bool = False # Boolean parameter with default
) -> str:
    # Schema will be automatically generated
    pass
```

Supported types:
- `str` → `"type": "string"`
- `int` → `"type": "integer"`
- `float` → `"type": "number"`
- `bool` → `"type": "boolean"`
- `list` → `"type": "array"`
- `dict` → `"type": "object"`
- `Optional[T]` → Same as `T` but not required

## Tool Patterns

### Single-Method Toolsets

For toolsets with only one function, the method parameters become the toolset parameters directly:

```python
class EchoToolset(Toolset):
    """Simple echo toolset."""
    
    @tool_method
    async def echo(self, message: str, repeat: int = 1) -> str:
        """Echo a message."""
        return (message + " ") * repeat

# Usage: await toolset.execute(message="Hello", repeat=3)
```

### Multi-Method Toolsets

For toolsets with multiple functions, an `action` parameter is automatically added:

```python
class FileOperationsToolset(Toolset):
    """Toolset for file operations."""
    
    @tool_method
    async def read_file(self, filepath: str) -> str:
        """Read file contents."""
        # Implementation here
        pass
    
    @tool_method
    async def write_file(self, filepath: str, content: str) -> str:
        """Write content to file."""
        # Implementation here
        pass

# Usage: await toolset.execute(action="read_file", read_file_filepath="/path/to/file")
```

## Migration from BaseTool

### Old Approach (BaseTool)

```python
class CalculateTool(BaseTool):
    @property
    def name(self) -> str:
        return "calculate"
    
    @property
    def description(self) -> str:
        return "Perform basic mathematical calculations"
    
    def get_schema(self) -> dict[str, Any]:
        return {
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Mathematical expression to calculate"
                    }
                },
                "required": ["expression"]
            }
        }
    
    async def execute(self, **kwargs) -> dict[str, Any]:
        expression = kwargs.get("expression", "")
        # Implementation...
        return {"success": True, "result": result, "tool_name": self.name}
```

### New Approach (Toolset)

```python
class CalculateToolset(Toolset):
    """Perform basic mathematical calculations."""
    
    @tool_method
    async def calculate(self, expression: str) -> str:
        """Calculate the result of a mathematical expression.
        
        Args:
            expression: Mathematical expression to calculate
            
        Returns:
            String representation of the calculation result
        """
        # Implementation...
        return f"{expression} = {result}"
```

### Migration Steps

1. **Change base class**: `BaseTool` → `Toolset`
2. **Move description to class docstring**: Remove `description` property
3. **Remove manual schema**: Delete `get_schema()` method
4. **Convert execute logic to decorated methods**: Break down `execute()` into specific methods
5. **Add type hints**: Use proper Python type hints for parameters
6. **Use adapter for compatibility**: Wrap with `ToolsetAdapter` if needed

## Integration with Existing System

The new toolsets are fully compatible with the existing system:

```python
from agentarea_agents_sdk.tools import ToolExecutor, ToolsetAdapter
from your_tools import MyToolset

# Create tool executor
executor = ToolExecutor()

# Register toolset
my_toolset = MyToolset()
adapter = ToolsetAdapter(my_toolset)
executor.register_tool(adapter)

# Use with agents
tools = executor.get_openai_functions()  # Works as before
result = await executor.execute_tool("my_toolset", {"param": "value"})
```

## Best Practices

1. **Use descriptive class names**: The toolset name is derived from the class name
2. **Write clear docstrings**: Both class and method docstrings are used for descriptions
3. **Use proper type hints**: They're used for schema generation
4. **Keep methods focused**: Each method should do one thing well
5. **Handle errors gracefully**: Use proper exception handling in methods
6. **Use async methods**: For consistency with the async execution model
7. **Group related functionality**: Put related methods together in a single toolset
8. **Use meaningful toolset names**: End class names with "Toolset" for clarity

## Examples

See `example_decorator_tool.py` for complete examples of:
- Mathematical operations toolset
- Data processing toolset  
- Simple single-method toolset
- File operations toolset

These examples demonstrate various patterns and best practices for using the toolset approach.

### Built-in Toolsets

The SDK includes several ready-to-use toolsets:

#### FileToolset

A comprehensive file operations toolset that provides:
- `save_file`: Write content to files with optional overwrite protection
- `read_file`: Read file contents with error handling
- `list_files`: List files in a directory with optional pattern filtering
- `search_files`: Search for files using glob patterns

```python
from pathlib import Path
from agentarea_agents_sdk.tools import FileToolset

# Create a file toolset with a specific base directory
file_toolset = FileToolset(base_dir=Path("/path/to/workspace"))

# Save a file
result = await file_toolset.execute(
    action="save_file", 
    contents="Hello, World!", 
    file_name="greeting.txt"
)

# Read the file
result = await file_toolset.execute(
    action="read_file", 
    file_name="greeting.txt"
)

# List all Python files
result = await file_toolset.execute(
    action="list_files", 
    pattern="*.py"
)

# Search for files recursively
result = await file_toolset.execute(
    action="search_files", 
    pattern="**/*.txt"
)
```

The FileToolset includes safety features:
- Automatic directory creation for nested paths
- Overwrite protection (configurable)
- Proper error handling and reporting
- Relative path handling within the base directory

## Backward Compatibility

The new toolset approach is fully backward compatible:

- Existing `BaseTool` implementations continue to work unchanged
- Both approaches can coexist in the same codebase
- Migration can be done gradually, one tool at a time
- The `ToolsetAdapter` ensures seamless integration with existing systems

## Conclusion

The toolset approach provides a more intuitive and maintainable way to create tools. It reduces boilerplate code, improves type safety, and makes tools easier to understand and modify.

Key benefits:
- ✅ Less boilerplate code
- ✅ Automatic schema generation
- ✅ Better type safety
- ✅ Clearer method organization
- ✅ Logical grouping of related functionality
- ✅ Full backward compatibility
- ✅ Easier testing and debugging
- ✅ Self-documenting through docstrings