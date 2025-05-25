# def main():
#     print("Hello from mcp-hub!")


# if __name__ == "__main__":
#     main()


import time
import sys
import signal
from typing import Any, Callable, Dict
import uuid
import anyio
import watchfiles
import anyio.from_thread
from anyio.streams.memory import MemoryObjectSendStream
import anyio.to_thread
from fastmcp import FastMCP
import uvicorn
import anyio.abc



from mcphub.orchestrator import MCPOrchestrator


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
    """Add two numbers"""
    return a + b

# Add a dynamic greeting resource
@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    """Get a personalized greeting"""
    return f"Hello, {name}!"

app = mcp.sse_app()

async def signal_handler(scope: anyio.abc.CancelScope):
    with anyio.open_signal_receiver(signal.SIGINT, signal.SIGTERM) as signals:
        async for signum in signals:
            if signum == signal.SIGINT:
                print('Ctrl+C pressed!')
            else:
                print('Terminated!')

            scope.cancel()
            return
        
async def process(num: int, sleep: float):
    while True:
        print(f"Worker {num} is performing...")
        await anyio.sleep(sleep)

class Manager:
    def __init__(self):
        self._tasks: Dict[int, anyio.CancelScope] = {}
        self._next_task_id = 0
        self._task_group: anyio.abc.TaskGroup = None
        self._lock = anyio.Lock()
        
    async def __aenter__(self):
        pass

    async def start(self) -> None:
        """Starts the task manager."""
        async with self._lock:
            if self._task_group is not None:
                raise RuntimeError("TaskManager is already started")
        self._task_group = anyio.create_task_group()
        await self._task_group.__aenter__()

    async def stop(self) -> None:
        """Stops the task manager and cancels all tasks."""
        async with self._lock:
            if self._task_group is None:
                return
        self._task_group.cancel_scope.cancel()
        await self._task_group.__aexit__(None, None, None)
        self._task_group = None
        self._tasks.clear()

    def start_task(self, coro_fn, *args, **kwargs):
        if self._task_group is None:
            raise RuntimeError("TaskManager must be used within an async context")
        
        task_id = self._next_task_id
        self._next_task_id += 1
        
        cancel_scope = anyio.CancelScope()
        self._tasks[task_id] = cancel_scope
        
        self._task_group.start_soon(
            self._run_task,
            task_id,
            cancel_scope,
            coro_fn,
            args,
            kwargs
        )
        return task_id
    
    async def _run_task(self, task_id, cancel_scope, coro_fn, args, kwargs):
        with cancel_scope:
            try:
                await coro_fn(*args, **kwargs)
            finally:
                self._tasks.pop(task_id, None)

    def stop_task(self, task_id):
        cancel_scope = self._tasks.get(task_id)
        if cancel_scope:
            cancel_scope.cancel()


    async def create_task(self, task_name: str, task_func: Callable[..., Any], *args, **kwargs) -> None:
        """Creates a new task."""
        async with self._lock:
            if task_name in self._tasks:
                raise ValueError(f"Task {task_name} already exists")
        if self._task_group is None:
            raise RuntimeError("TaskManager is not started")

        async def task_wrapper() -> None:
            try:
                await task_func(*args, **kwargs)
            except anyio.get_cancelled_exc_class():
                print(f"Task {task_name} was cancelled")

            cancel_scope = await self._task_group.start(task_wrapper)
            # anyio task groups do not return a cancel scope directly
            # we need to use the task_group's cancel_scope to cancel tasks
            self._tasks[task_name] = task_name  # store task name instead of cancel scope

    async def cancel_task(self, task_name: str) -> None:
        """Cancels a task by name."""
        async with self._lock:
            if task_name not in self._tasks:
                raise ValueError(f"Task {task_name} not found")
        # Since we can't directly cancel a task in anyio,
        # we need to keep track of tasks and cancel them using their name or other means
        # For simplicity, we're just removing the task from the dictionary
        del self._tasks[task_name]
        # For actual task cancellation, consider using a different approach, like task groups or workers



    async def __aexit__(self):
        pass

async def main():
    print("Run test process ...")

    # process1 = await anyio.open_process(['uvx', 'mcp-server-fetch'], stdout=sys.stdout)
    # process2 = await anyio.open_process(['npx', '-y', '@delorenj/mcp-server-trello'], stdout=sys.stdout);
    # process3 = await anyio.open_process(['ping', '77.88.8.8'], stdout=sys.stdout)

    # async with anyio.create_task_group() as tg:
        # tg.start_soon(process1.wait)
        # tg.start_soon(process2.wait)
    # async with (
    #     anyio.create_task_group() as tg,
    #     process1,
    #     process2,
    #     process3
    # ):
    #     print("alala")
    manager = Manager()

    async with anyio.create_task_group() as tg:
        try:
            await manager.start()
            tg.start_soon(process, 100, 2)
            t1 = manager.start_task(process, 1, 1)
            t2 = manager.start_task(process, 2, 1)
            t3 = manager.start_task(process, 3, 1)
            await anyio.sleep(10)
            manager.stop_task(t2)
        finally:
            await manager.stop()  

    # async with anyio.create_task_group() as tg:
    #     tg.start_soon(signal_handler, tg.cancel_scope)
        
        


if __name__ == "__main__":
    anyio.run(main)
