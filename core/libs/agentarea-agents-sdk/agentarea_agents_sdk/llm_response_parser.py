"""LLM Response Parser

Handles parsing of LiteLLM responses, including extraction of tool calls 
from various response formats.
"""

import json
import logging
import re
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class LiteLLMResponseParser:
    """Parser for LiteLLM responses with proper tool call extraction."""

    @staticmethod
    def parse_response(response: Any) -> dict[str, Any]:
        """Parse LiteLLM response into standardized format.
        
        Args:
            response: Raw LiteLLM response object
            
        Returns:
            Dict containing parsed response data
        """
        parsed = {
            "role": "assistant",
            "content": "",
            "tool_calls": None,
            "usage": None,
            "cost": 0.0
        }

        # Handle response based on structure
        if hasattr(response, 'choices') and response.choices:
            choice = response.choices[0]
            message = choice.message

            # Extract content
            if hasattr(message, 'content') and message.content:
                parsed["content"] = message.content

            # Extract structured tool calls first
            if hasattr(message, 'tool_calls') and message.tool_calls:
                parsed["tool_calls"] = LiteLLMResponseParser._format_tool_calls(message.tool_calls)
            else:
                # Try to extract from content if no structured tool calls
                extracted_calls = LiteLLMResponseParser._extract_tool_calls_from_content(parsed["content"])
                if extracted_calls:
                    parsed["tool_calls"] = extracted_calls
                    logger.info(f"Extracted {len(extracted_calls)} tool calls from content")

        # Extract usage information
        if hasattr(response, 'usage') and response.usage:
            parsed["usage"] = {
                "prompt_tokens": getattr(response.usage, 'prompt_tokens', 0),
                "completion_tokens": getattr(response.usage, 'completion_tokens', 0),
                "total_tokens": getattr(response.usage, 'total_tokens', 0),
            }

            # Calculate cost if available
            cost = 0.0
            if hasattr(response.usage, 'completion_tokens_cost'):
                cost += getattr(response.usage, 'completion_tokens_cost', 0.0)
            if hasattr(response.usage, 'prompt_tokens_cost'):
                cost += getattr(response.usage, 'prompt_tokens_cost', 0.0)
            elif hasattr(response.usage, 'total_tokens'):
                # Fallback estimate
                cost = getattr(response.usage, 'total_tokens', 0) * 0.00001

            parsed["cost"] = cost

        return parsed

    @staticmethod
    def _format_tool_calls(tool_calls: list[Any]) -> list[dict[str, Any]]:
        """Format structured tool calls into standard format."""
        formatted = []

        for i, tc in enumerate(tool_calls):
            formatted_call = {
                "id": getattr(tc, 'id', f"call_{i}"),
                "type": "function",
                "function": {
                    "name": getattr(tc.function, 'name', ''),
                    "arguments": getattr(tc.function, 'arguments', '{}')
                }
            }
            formatted.append(formatted_call)

        return formatted

    @staticmethod
    def _extract_tool_calls_from_content(content: str) -> list[dict[str, Any]]:
        """Extract tool calls from LLM content when returned as JSON text.
        
        This handles cases where LLMs return tool calls as JSON in the content
        field instead of using structured tool_calls.
        """
        if not content or not content.strip():
            return []

        tool_calls = []

        try:
            # Primary method: Try to parse entire content as JSON
            try:
                parsed = json.loads(content.strip())
                if isinstance(parsed, dict) and parsed.get("name") == "task_complete":
                    arguments = parsed.get("arguments", {})
                    tool_calls.append({
                        "id": f"extracted_{uuid4().hex[:8]}",
                        "type": "function",
                        "function": {
                            "name": "task_complete",
                            "arguments": json.dumps(arguments) if isinstance(arguments, dict) else str(arguments)
                        }
                    })
                    logger.debug("Extracted tool call from JSON content: task_complete")
                    return tool_calls
            except json.JSONDecodeError:
                pass

            # Secondary method: Pattern matching for JSON-like structures
            patterns = [
                # {"name": "task_complete", "arguments": {...}}
                r'\{\s*["\']name["\']\s*:\s*["\']task_complete["\']\s*,\s*["\']arguments["\']\s*:\s*(\{[^}]*\})\s*\}',
                # Looser pattern matching
                r'["\']name["\']\s*:\s*["\']task_complete["\']\s*,\s*["\']arguments["\']\s*:\s*(\{[^}]*\})',
            ]

            for pattern in patterns:
                matches = re.findall(pattern, content, re.IGNORECASE | re.DOTALL)
                for match in matches:
                    try:
                        args = json.loads(match) if match.strip().startswith('{') else {"result": match.strip()}
                        tool_calls.append({
                            "id": f"extracted_{uuid4().hex[:8]}",
                            "type": "function",
                            "function": {
                                "name": "task_complete",
                                "arguments": json.dumps(args)
                            }
                        })
                        logger.debug("Extracted tool call from pattern match")
                        break
                    except json.JSONDecodeError:
                        continue

            # Fallback: Simple keyword detection
            if not tool_calls and "task_complete" in content.lower():
                tool_calls.append({
                    "id": f"fallback_{uuid4().hex[:8]}",
                    "type": "function",
                    "function": {
                        "name": "task_complete",
                        "arguments": json.dumps({"result": content.strip()})
                    }
                })
                logger.debug("Fallback tool call extraction for task_complete")

        except Exception as e:
            logger.warning(f"Failed to extract tool calls from content: {e}")

        return tool_calls

    @staticmethod
    def parse_streaming_tool_calls(tool_calls_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Build tool calls from streamed tool call data.
        
        Based on agno library approach for handling streaming responses.
        """
        if not tool_calls_data:
            return []

        # Group tool calls by index
        tool_calls_by_index: dict[int, dict[str, Any]] = {}

        for tc in tool_calls_data:
            index = tc.get("index", 0)
            if not isinstance(index, int):
                index = 0

            # Initialize if first time seeing this index
            if index not in tool_calls_by_index:
                tool_calls_by_index[index] = {
                    "id": None,
                    "type": "function",
                    "function": {"name": "", "arguments": ""}
                }

            # Update with new information
            if tc.get("id") is not None:
                tool_calls_by_index[index]["id"] = tc["id"]

            if tc.get("type") is not None:
                tool_calls_by_index[index]["type"] = tc["type"]

            # Update function information
            function_data = tc.get("function", {})
            if isinstance(function_data, dict):
                if function_data.get("name") is not None:
                    tool_calls_by_index[index]["function"]["name"] = function_data["name"]

                if function_data.get("arguments") is not None:
                    current_args = tool_calls_by_index[index]["function"]["arguments"]
                    new_args = function_data["arguments"]
                    if isinstance(current_args, str) and isinstance(new_args, str):
                        tool_calls_by_index[index]["function"]["arguments"] = current_args + new_args

        # Process and validate arguments
        result = []
        for tc in tool_calls_by_index.values():
            tc_copy = {
                "id": tc.get("id"),
                "type": tc.get("type", "function"),
                "function": {"name": "", "arguments": ""}
            }

            if isinstance(tc.get("function"), dict):
                func_dict = tc["function"]
                tc_copy["function"]["name"] = func_dict.get("name", "")

                # Ensure arguments are valid JSON
                args = func_dict.get("arguments", "")
                if args and isinstance(args, str):
                    try:
                        parsed = json.loads(args)
                        if not isinstance(parsed, dict):
                            tc_copy["function"]["arguments"] = json.dumps({"value": parsed})
                        else:
                            tc_copy["function"]["arguments"] = args
                    except json.JSONDecodeError:
                        tc_copy["function"]["arguments"] = json.dumps({"text": args})

            result.append(tc_copy)

        return result
