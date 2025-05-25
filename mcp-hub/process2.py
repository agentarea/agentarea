import anyio
from typing import Callable, Dict, Any

class TaskManager:
    """Manages a collection of asynchronous tasks."""

    def __init__(self):
        self._tasks: Dict[str, str] = {}
        self._task_group = None
        self._lock = anyio.Lock()

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

    async def create_task(
        self, task_name: str, task_func: Callable[..., Any], *args, **kwargs
    ) -> None:
        """Creates a new task."""
        async with self._lock:
            if task_name in self._tasks:
                raise ValueError(f"Task {task_name} already exists")
            
            async def task_wrapper() -> None:
                try:
                    await task_func(*args, **kwargs)
                except anyio.get_cancelled_exc_class():
                    ...
                    # print(f"----Task {task_name} was cancelled")

            async def task_runner() -> None:
                async with anyio.create_task_group() as tg:
                    tg.start_soon(task_wrapper)
                    self._tasks[task_name] = tg.cancel_scope

            self._task_group.start_soon(task_runner)

    async def cancel_task(self, task_name: str) -> None:
        """Cancels a task by name."""
        async with self._lock:
            if task_name not in self._tasks:
                raise ValueError(f"Task {task_name} not found")
            # del self._tasks[task_name]
            self._tasks[task_name].cancel()


class AsyncApp:
    """An example asynchronous application."""

    def __init__(self):
        self.task_manager = TaskManager()

    async def start(self) -> None:
        """Starts the application."""
        await self.task_manager.start()

    async def stop(self) -> None:
        """Stops the application."""
        await self.task_manager.stop()

    async def run(self) -> None:
        """Runs the application."""
        try:
            await self.start()
            await self._run_tasks()
        finally:
            await self.stop()

    async def _run_tasks(self) -> None:
        """Creates and manages tasks."""
        tasks = [
            ("task1", long_running_task, ("Task1",), {"description": "hello kwargs"}),
            ("task2", long_running_task, ("Task2",), {}),
            ("task3", long_running_task, ("Task3",), {}),
        ]

        for task_name, task_func, args, kwargs in tasks:
            await self.task_manager.create_task(task_name, task_func, *args, **kwargs)

        await anyio.sleep(3)
        await self.task_manager.cancel_task("task2")
        await anyio.sleep(4)


async def long_running_task(task_id: str, description: str = "") -> None:
    """A long-running task."""
    try:
        for i in range(10):
            print(f"Task {task_id}: {i}, description: {description}")
            await anyio.sleep(1)
    except anyio.get_cancelled_exc_class():
        ...
        # print(f"Task {task_id} was cancelled")


async def main() -> None:
    """The main entry point."""
    async_app = AsyncApp()
    await async_app.run()


if __name__ == "__main__":
    anyio.run(main)