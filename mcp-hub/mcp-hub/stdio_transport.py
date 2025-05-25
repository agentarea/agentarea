import contextlib
from collections.abc import AsyncIterator
from typing import Unpack

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from fastmcp.client.transports import ClientTransport, SessionKwargs
from mcp import ClientSession, types


@contextlib.asynccontextmanager
async def stdio_client(stdin: MemoryObjectSendStream[str], stdout: MemoryObjectReceiveStream[str]):
    """Client transport for stdio.

    This will connect to a server by spawning a
    process and communicating with it over stdin/stdout.
    """
    read_stream: MemoryObjectReceiveStream[types.JSONRPCMessage | Exception]
    read_stream_writer: MemoryObjectSendStream[types.JSONRPCMessage | Exception]

    write_stream: MemoryObjectSendStream[types.JSONRPCMessage]
    write_stream_reader: MemoryObjectReceiveStream[types.JSONRPCMessage]

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    async def stdout_reader():
        try:
            async with read_stream_writer:
                async for line in stdout:
                    try:
                        message = types.JSONRPCMessage.model_validate_json(line)
                    except Exception as exc:
                        await read_stream_writer.send(exc)
                        continue

                    await read_stream_writer.send(message)
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()

    async def stdin_writer():
        try:
            async with write_stream_reader:
                async for message in write_stream_reader:
                    json = message.model_dump_json(by_alias=True, exclude_none=True)
                    await stdin.send((json + "\n").encode())
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()

    async with (
        anyio.create_task_group() as tg,
    ):
        tg.start_soon(stdout_reader)
        tg.start_soon(stdin_writer)
        yield read_stream, write_stream


class StdioTransport(ClientTransport):
    """Custom transport for connecting to an MCP server via stdio .

    This is a base class that can be subclassed for specific command-based
    transports like Python, Node, Uvx, etc.
    """

    def __init__(
        self,
        stdin: MemoryObjectSendStream[str],
        stdout: MemoryObjectReceiveStream[str],
    ):
        """Initialize a Stdio transport.

        Args:
            stdin: The stdin stream
            stdout: The stdout lines stream
        """
        self.stdin = stdin
        self.stdout = stdout

    @contextlib.asynccontextmanager
    async def connect_session(
        self, **session_kwargs: Unpack[SessionKwargs]
    ) -> AsyncIterator[ClientSession]:
        async with stdio_client(self.stdin, self.stdout) as transport:
            read_stream, write_stream = transport
            async with ClientSession(read_stream, write_stream, **session_kwargs) as session:
                await session.initialize()
                yield session

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(stdin='{self.stdin}', stdout={self.stdout})>"
