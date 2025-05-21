import os
import asyncio
import logging
import agentops

import dotenv


dotenv.load_dotenv()


AGENTOPS_API_KEY = os.getenv("AGENTOPS_API_KEY")
agentops.init(api_key=AGENTOPS_API_KEY, default_tags=["litellm"])

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, SseServerParams
from google.adk.tools import apihub_tool
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

    tools, exit_stack = await MCPToolset.from_server(connection_params=sse_params)
    logger.info(f"Connected to MCP Web server. Found {len(tools)} tools.")
    return tools, exit_stack


async def get_twitter_agent_1(llm):
    # Define basic Twitter-like mock tools for managing a Twitter account
    # These are in-memory mock implementations with simulated responses

    # In-memory storage for our mock Twitter data
    twitter_mock_data = {
        "tweets": [
            {
                "id": "1",
                "content": "Hello Twitter! #FirstTweet",
                "likes": 5,
                "retweets": 2,
                "timestamp": "2023-06-15T10:30:00Z",
            },
            {
                "id": "2",
                "content": "Just launched our new product! Check it out at example.com",
                "likes": 42,
                "retweets": 15,
                "timestamp": "2023-06-16T14:22:00Z",
            },
            {
                "id": "3",
                "content": "Excited to announce our partnership with @BigCompany! #Partnership",
                "likes": 87,
                "retweets": 31,
                "timestamp": "2023-06-18T09:15:00Z",
            },
        ],
        "following": ["techguru", "newsupdate", "influencer123"],
        "followers": ["fan1", "fan2", "supporter99", "industry_expert"],
        "mentions": [
            {
                "id": "m1",
                "username": "competitor",
                "content": "I think @our_account has a better product than us",
                "timestamp": "2023-06-17T11:20:00Z",
            },
            {
                "id": "m2",
                "username": "customer",
                "content": "Hey @our_account, love your service! #Recommendation",
                "timestamp": "2023-06-18T16:45:00Z",
            },
        ],
    }

    # Mock function implementations
    def mock_post_tweet(content, media_urls=None):
        new_id = str(len(twitter_mock_data["tweets"]) + 1)
        new_tweet = {
            "id": new_id,
            "content": content,
            "likes": 0,
            "retweets": 0,
            "timestamp": "2023-06-19T08:00:00Z",  # Mock current time
            "media": media_urls if media_urls else [],
        }
        twitter_mock_data["tweets"].append(new_tweet)
        return {
            "status": "success",
            "tweet_id": new_id,
            "message": f"Tweet posted successfully: '{content}'",
        }

    def mock_get_timeline(count=10):
        return {"status": "success", "tweets": twitter_mock_data["tweets"][:count]}

    def mock_search_tweets(query, count=10):
        results = [
            tweet
            for tweet in twitter_mock_data["tweets"]
            if query.lower() in tweet["content"].lower()
        ]
        return {"status": "success", "query": query, "results": results[:count]}

    def mock_follow_user(username):
        if username in twitter_mock_data["following"]:
            return {"status": "warning", "message": f"Already following @{username}"}
        twitter_mock_data["following"].append(username)
        return {"status": "success", "message": f"Now following @{username}"}

    def mock_unfollow_user(username):
        if username not in twitter_mock_data["following"]:
            return {
                "status": "warning",
                "message": f"Not currently following @{username}",
            }
        twitter_mock_data["following"].remove(username)
        return {"status": "success", "message": f"Unfollowed @{username}"}

    def mock_get_user_info(username):
        # Simulate different user profiles
        if username in twitter_mock_data["following"]:
            return {
                "status": "success",
                "username": username,
                "display_name": username.title(),
                "followers_count": 1500 + hash(username) % 10000,
                "following_count": 500 + hash(username) % 1000,
                "tweet_count": 1200 + hash(username) % 5000,
                "bio": f"This is a mock profile for {username}",
                "is_following": True,
            }
        return {
            "status": "success",
            "username": username,
            "display_name": username.title(),
            "followers_count": 1500 + hash(username) % 10000,
            "following_count": 500 + hash(username) % 1000,
            "tweet_count": 1200 + hash(username) % 5000,
            "bio": f"This is a mock profile for {username}",
            "is_following": False,
        }

    def mock_get_mentions(count=10):
        return {"status": "success", "mentions": twitter_mock_data["mentions"][:count]}

    # Define Twitter tools with mock implementations
    twitter_tools = [
        {
            "name": "post_tweet",
            "description": "Post a new tweet to the Twitter account",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The text content of the tweet",
                    },
                    "media_urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of media URLs to attach to the tweet",
                    },
                },
                "required": ["content"],
            },
            "function": mock_post_tweet,
        },
        {
            "name": "get_timeline",
            "description": "Retrieve the latest tweets from the user's timeline",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "description": "Number of tweets to retrieve (default: 10)",
                    }
                },
            },
            "function": mock_get_timeline,
        },
        {
            "name": "search_tweets",
            "description": "Search for tweets using a specific query",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (hashtags, keywords, etc.)",
                    },
                    "count": {
                        "type": "integer",
                        "description": "Number of results to return (default: 10)",
                    },
                },
                "required": ["query"],
            },
            "function": mock_search_tweets,
        },
        {
            "name": "follow_user",
            "description": "Follow a Twitter user",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "Twitter username to follow (without the @ symbol)",
                    }
                },
                "required": ["username"],
            },
            "function": mock_follow_user,
        },
        {
            "name": "unfollow_user",
            "description": "Unfollow a Twitter user",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "Twitter username to unfollow (without the @ symbol)",
                    }
                },
                "required": ["username"],
            },
            "function": mock_unfollow_user,
        },
        {
            "name": "get_user_info",
            "description": "Get information about a Twitter user",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "Twitter username (without the @ symbol)",
                    }
                },
                "required": ["username"],
            },
            "function": mock_get_user_info,
        },
        {
            "name": "get_mentions",
            "description": "Get tweets that mention the user",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "description": "Number of mentions to retrieve (default: 10)",
                    }
                },
            },
            "function": mock_get_mentions,
        },
    ]

    # Combine Twitter tools with MCP tools
    combined_tools = twitter_tools
    llm_agent = LlmAgent(
        model=llm,
        name="twitter_agent",
        instruction="You are a helpful assistant that manages a Twitter account. Use the appropriate tools to help users manage their Twitter account.",
        tools=combined_tools,
    )
    return llm_agent


async def get_agent_2():
        llm_agent = LlmAgent(
        model=llm,
        name="task_assistant",
        instruction="You are a helpful assistant that manages tasks using the available tools. Use the appropriate tools to help users manage their tasks.",
        tools=combined_tools,
    )
    pass


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
        name="task_assistant",
        instruction="You are a helpful assistant that manages tasks using the available tools. Use the appropriate tools to help users manage their tasks.",
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
        content = types.Content(role="user", parts=[types.Part(text=query)])

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
        "Tell me about the server and analyze how many completed vs incomplete tasks I have",
    ]

    # Run all test queries
    for query in test_queries:
        await send_query(query)

    # Don't forget to properly close all exit stacks when done
    for stack in exit_stacks:
        await stack.aclose()  # Using close() instead of aclose() for regular ExitStack


if __name__ == "__main__":
    asyncio.run(main())
