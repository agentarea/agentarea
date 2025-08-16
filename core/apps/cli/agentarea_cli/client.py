"""HTTP client for AgentArea API communication."""

import asyncio
from typing import Any

import click
import httpx

from .config import AuthConfig
from .exceptions import (
    AgentAreaError,
    AuthenticationError,
)
from .exceptions import (
    APIError as AgentAreaAPIError,
)


class AgentAreaClient:
    """HTTP client for communicating with AgentArea API."""

    def __init__(self, base_url: str, auth_config: AuthConfig, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.auth_config = auth_config
        self.timeout = timeout

    def _get_headers(self) -> dict[str, str]:
        """Get headers including authentication."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "AgentArea-CLI/1.0"
        }

        token = self.auth_config.get_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        else:
            # Default token for local development
            headers["Authorization"] = "Bearer simple-test-token"

        # Add required user context headers for development
        headers["X-User-ID"] = "test-user-123"
        headers["X-Workspace-ID"] = "test-workspace-456"

        return headers

    async def request(
        self,
        method: str,
        endpoint: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make HTTP request to the API."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            url = f"{self.base_url}{endpoint}"
            headers = self._get_headers()

            try:
                response = await self._make_request(
                    client, method, url, headers, data, params
                )
                return await self._handle_response(response)

            except httpx.ConnectError as e:
                raise AgentAreaAPIError(
                    f"Cannot connect to API server at {self.base_url}. "
                    "Make sure the API server is running."
                ) from e
            except httpx.TimeoutException as e:
                raise AgentAreaAPIError(f"Request timeout after {self.timeout}s") from e
            except httpx.HTTPStatusError as e:
                await self._handle_http_error(e)

    async def _make_request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        headers: dict[str, str],
        data: dict[str, Any] | None,
        params: dict[str, Any] | None
    ) -> httpx.Response:
        """Make the actual HTTP request."""
        method = method.upper()

        if method == "GET":
            response = await client.get(url, headers=headers, params=params)
        elif method == "POST":
            response = await client.post(url, json=data, headers=headers, params=params)
        elif method == "PUT":
            response = await client.put(url, json=data, headers=headers, params=params)
        elif method == "DELETE":
            response = await client.delete(url, headers=headers, params=params)
        elif method == "PATCH":
            response = await client.patch(url, json=data, headers=headers, params=params)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        response.raise_for_status()
        return response

    async def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle successful response."""
        if response.status_code == 204:  # No Content
            return {}

        try:
            return response.json()
        except ValueError as e:
            raise AgentAreaAPIError(f"Invalid JSON response: {e}") from e

    async def _handle_http_error(self, error: httpx.HTTPStatusError) -> None:
        """Handle HTTP errors with appropriate exceptions."""
        status_code = error.response.status_code

        try:
            error_data = error.response.json()
            error_message = error_data.get("detail", error.response.text)
        except ValueError:
            error_message = error.response.text

        if status_code == 401:
            raise AuthenticationError(
                "Authentication failed. Please login first with 'agentarea auth login'"
            ) from error
        elif status_code == 403:
            raise AuthenticationError(
                "Access forbidden. You don't have permission for this operation."
            ) from error
        elif status_code == 404:
            raise AgentAreaAPIError(f"Resource not found: {error_message}") from error
        elif 400 <= status_code < 500:
            raise AgentAreaAPIError(f"Client error ({status_code}): {error_message}") from error
        elif 500 <= status_code < 600:
            raise AgentAreaAPIError(f"Server error ({status_code}): {error_message}") from error
        else:
            raise AgentAreaAPIError(f"HTTP {status_code}: {error_message}") from error

    # Convenience methods for common operations
    async def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make GET request."""
        return await self.request("GET", endpoint, params=params)

    async def post(self, endpoint: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make POST request."""
        return await self.request("POST", endpoint, data=data)

    async def put(self, endpoint: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make PUT request."""
        return await self.request("PUT", endpoint, data=data)

    async def delete(self, endpoint: str) -> dict[str, Any]:
        """Make DELETE request."""
        return await self.request("DELETE", endpoint)

    async def patch(self, endpoint: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make PATCH request."""
        return await self.request("PATCH", endpoint, data=data)


def run_async(coro):
    """Helper to run async functions in CLI commands."""
    try:
        return asyncio.run(coro)
    except KeyboardInterrupt:
        click.echo("\n❌ Operation cancelled by user")
        raise click.Abort()
    except Exception as e:
        if isinstance(e, (AgentAreaAPIError, AuthenticationError, AgentAreaError)):
            click.echo(f"❌ {e}")
        else:
            click.echo(f"❌ Unexpected error: {e}")
        raise click.Abort()
