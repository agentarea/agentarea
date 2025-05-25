import logging
import signal

import anyio
import uvicorn
import watchfiles
from fastmcp import FastMCP

from mcphub.orchestrator import MCPOrchestrator
from mcphub.process_manager import ProcessManager

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


async def watch_files(path: str):
    print(f"Start watching files in {path} ...")

    def only_changed(change: watchfiles.Change, path: str) -> bool:
        return change != watchfiles.Change.added

    async for changes in watchfiles.awatch('.'):
        print(changes)


# Create an MCP server
mcp = FastMCP("Demo")

# Add an addition tool
@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

# Add a dynamic greeting resource
@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    """Get a personalized greeting."""
    return f"Hello, {name}!"

app = mcp.http_app()

async def signal_handler(scope: anyio.abc.CancelScope):
    with anyio.open_signal_receiver(signal.SIGINT, signal.SIGTERM) as signals:
        async for signum in signals:
            if signum == signal.SIGINT:
                print('Ctrl+C pressed!')
            else:
                print('Terminated!')

            scope.cancel()
            return

async def main():
    print("MCP server is running using SSE transport ...")

    async with anyio.create_task_group() as tg:
        tg.start_soon(signal_handler, tg.cancel_scope)

        orchestrator = MCPOrchestrator("file", {"file_path": "mcp_servers.yaml"})
        # async with orchestrator:
        tg.start_soon(orchestrator.start)

        # try:
        #     manager = ProcessManager()

        #     async def init_manager():
        #         await manager.start()
        #         await manager.create_process('pinggoogle', 'ping', ['8.8.8.8'])
        #         await manager.create_process('pingyandex', 'ping', ['77.88.8.8'])
        #         await anyio.sleep(3)
        #         await manager.destroy_process('pinggoogle')

        #     # await tg.start(manager.start)
        #     tg.start_soon(init_manager)

        #     # await manager.create_process('pinggoogle', 'ping', ['8.8.8.8'])
        #     # await manager.create_process('pingyandex', 'ping', ['77.88.8.8'])

        #     await anyio.sleep(5)

        #     # tg.cancel_scope.cancel()

        #     await manager.destroy_process('pinggoogle')

        #     # await anyio.sleep(10)

        #     while True:
        #         await anyio.sleep(1)

        #     # await manager.destroy_process('pingyandex')
        # except BaseException as e:
        #     logging.exception(e)
        #     raise

        # finally:
        #     logging.info("Final clean up. Stopping manager...")
        #     await manager.stop()



        # tg.start_soon(watch_files, ".")

        # config = uvicorn.Config(
        #     app,
        #     host="0.0.0.0",
        #     port=8888,
        #     log_level="debug",
        #     reload=True,
        # )
        # server = uvicorn.Server(config)
        # await server.serve()


if __name__ == "__main__":
    anyio.run(main)
