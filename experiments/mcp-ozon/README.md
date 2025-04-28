# MCP Web Agent

An AI agent built with Google's Agent Development Kit (ADK) that connects to a running Model Context Protocol (MCP) web server using SSE (Server-Sent Events).

## Setup

1. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

2. Install the dependencies:
   ```bash
   pip install -e .
   ```

3. (Optional) Set up environment variables in a `.env` file:
   ```
   GOOGLE_API_KEY=your_gemini_api_key_here
   MCP_SERVER_URL=http://your-mcp-server-url/sse
   ```

   If `MCP_SERVER_URL` is not specified, the agent will default to `http://localhost:3000/sse`.

## Running the Agent

Simply run the agent which will connect to the already running MCP web server:

```bash
python main.py
```

This will:
1. Connect your ADK agent to the MCP web server via SSE
2. Open an interactive chat interface

## Available Web Tools

The MCP web server provides tools for:
- Loading web pages
- Extracting content from web pages
- Capturing screenshots
- Searching within web content

## Usage Examples

Once the agent is running, you can ask it to:
- "Load the webpage at example.com"
- "Extract the main content from the current page"
- "Search for information about AI on the current page"

## Troubleshooting

- If connection fails, verify the MCP server is running with SSE support
- Check that the server is accessible at the configured URL
- If the MCP server uses a different URL than the default, set the `MCP_SERVER_URL` environment variable
