import os
import asyncio
import logging
import agentops

import dotenv


dotenv.load_dotenv()


AGENTOPS_API_KEY = os.getenv("AGENTOPS_API_KEY") or 'eeeeef4d-3443-422a-8903-019a857c7d8c'
agentops.init(
    api_key=AGENTOPS_API_KEY,
    default_tags=['litellm']
)
 
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, SseServerParams
from google.adk.models.lite_llm import LiteLlm
from google.genai import types

# Configure logging to avoid LiteLLM logging errors
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Disable LiteLLM's default logging to prevent annotation errors
logging.getLogger("litellm").setLevel(logging.ERROR)

lite_llm = LiteLlm(
    # model="openrouter/google/gemini-2.0-flash-001",
    model=os.getenv("OPENAI_MODEL"),
    api_key=os.getenv("OPENROUTER_API_KEY"),
    # base_url="https://openrouter.ai/api/v1",
)

# Load environment variables from .env file if it exists
# Get MCP server URL from environment variable or use default
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:3000/sse")

# Define the async function to get MCP tools
async def get_mcp_tools(server_url: str):
    """Gets tools from the MCP Web Server using SSE connection."""
    logger.info(f"Connecting to MCP Web server at: {server_url}")
    
    sse_params = SseServerParams(
        url=server_url,
        headers={},
    )
    
    tools, exit_stack = await MCPToolset.from_server(
        connection_params=sse_params
    )
    logger.info(f"Connected to MCP Web server. Found {len(tools)} tools.")
    return tools, exit_stack

async def main():
    # Run the async function to get tools using asyncio.run
    server_urls = ["http://localhost:3001/sse"]
    combined_tools = []
    exit_stacks = []

    # Iterate over server URLs and collect tools
    for server_url in server_urls:
        tools, exit_stack = await get_mcp_tools(server_url=server_url)
        combined_tools.extend(tools)
        exit_stacks.append(exit_stack)

    user_id = "user_1"
    app_name = "mcp_task_manager_app"
    session_service = InMemorySessionService()
    session = session_service.create_session(
          state={}, app_name=app_name, user_id=user_id
      )
    
    def log_callback(**kwargs):
        logger.info(f"Callback: {kwargs}")

    agent = LlmAgent(
        model=lite_llm,
        name='task_assistant',
        instruction='You are a helpful assistant that manages tasks using the available tools. Use the appropriate tools to help users manage their tasks.',
        tools=combined_tools,
        # before_agent_callback=log_callback,
        # after_model_callback=log_callback,
        # before_tool_callback=log_callback,
        # after_tool_callback=log_callback,
    )

    # Create a runner with the agent
    runner = Runner(
        app_name=app_name,
        agent=agent,
        session_service=session_service,
    )

    # Function to send a query and get response (non-async version)
    async def send_query(query):
        content = types.Content(role='user', parts=[types.Part(text=query)])
        
        # Send message to the agent
        response = runner.run_async(
            session_id=session.id,
            user_id=user_id,
            new_message=content,
        )
        
        logger.info(f"\n--- Query: {query} ---")
        async for event in response:
            logger.info(f"Event received: {event}")
        logger.info("-------------------\n")

    # Test all the task management flows
    test_queries = [
        # Complex task management flow
        # "Add a task called 'Write documentation', then mark it as completed, and show me all tasks",
        
        # Multiple operations in one query
        "Add two tasks: 'Prepare presentation' and 'Schedule meeting', then delete the 'Prepare presentation' task, and show me the final list",
        
        # Complex conditional operation
        "Add a task called 'Call client', and if there are more than 3 tasks in total, delete the oldest one, then list all tasks",
        
        # Multi-step task with verification
        "Create a task called 'Review code', mark it as completed, then create another task called 'Deploy code', and tell me which tasks are still pending",
        
        # Get server information and perform analysis
        "Tell me about the server and analyze how many completed vs incomplete tasks I have"
    ]

    # Run all test queries
    for query in test_queries:
        await send_query(query)

    # Don't forget to properly close all exit stacks when done
    for stack in exit_stacks:
        await stack.aclose()  # Using close() instead of aclose() for regular ExitStack

if __name__ == "__main__":
    asyncio.run(main())
