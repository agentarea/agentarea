import contextlib
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import typing
import uuid
from typing import Any

import anyio


class ProcessDefinition:
    """Represents the definition of a process to be managed.  This should only
    hold the *configuration* needed to launch a process, and must be serializable.
    """

    def __init__(
        self, command: list[str], env: dict[str, str] | None = None, cwd: str | None = None
    ):
        if (
            not command
            or not isinstance(command, list)
            or not all(isinstance(arg, str) for arg in command)
        ):
            raise ValueError("Command must be a non-empty list of strings.")

        if env is not None and not isinstance(env, dict):
            raise ValueError("Env must be a dictionary.")

        if cwd is not None and not isinstance(cwd, str):
            raise ValueError("Cwd must be a string.")

        self.command = command
        self.env = env or {}
        self.cwd = cwd

    def to_dict(self) -> dict[str, Any]:
        """Serializes the process definition to a dictionary.  Useful for persistence."""
        return {"command": self.command, "env": self.env, "cwd": self.cwd}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProcessDefinition":
        """Creates a ProcessDefinition from a dictionary (e.g., loaded from JSON)."""
        return cls(command=data.get("command"), env=data.get("env"), cwd=data.get("cwd"))


class ManagedProcess:
    """Represents a running process managed by the DockerProcessManager.

    Holds the subprocess.Popen object, stdout/stderr queues, and methods interaction.
    """

    def __init__(self, process_id: str, process_definition: ProcessDefinition):
        self.process_id = process_id
        self.process_definition = process_definition
        self.process: subprocess.Popen | None = None
        self.stdout_queue: queue.Queue = queue.Queue()
        self.stderr_queue: queue.Queue = queue.Queue()
        self.running: bool = False
        self.returncode: int | None = None
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None

    def start(self) -> None:
        """Starts the managed process."""
        try:
            self.process = subprocess.Popen(
                self.process_definition.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                env=self.process_definition.env,
                cwd=self.process_definition.cwd,  # Added cwd
                text=True,  # Added text=True for easier handling of stdout/stderr as strings
            )
            self.running = True
            self._stdout_thread = threading.Thread(
                target=self._enqueue_output, args=(self.process.stdout, self.stdout_queue)
            )
            self._stderr_thread = threading.Thread(
                target=self._enqueue_output, args=(self.process.stderr, self.stderr_queue)
            )
            self._stdout_thread.daemon = True  # Allow main thread to exit even if these are running
            self._stderr_thread.daemon = True

            self._stdout_thread.start()
            self._stderr_thread.start()

            logging.info(f"Process {self.process_id} started with PID {self.process.pid}")
        except Exception as e:
            logging.error(f"Error starting process {self.process_id}: {e}")
            self.running = False

    def stop(self, timeout: float = 10.0) -> None:
        """Stops the managed process."""
        if not self.running or self.process is None:
            logging.warning(
                f"Process {self.process_id} is not running or process is None, cannot stop."
            )
            return

        logging.info(f"Stopping process {self.process_id}")
        try:
            self.process.terminate()  # Send SIGTERM
            self.process.wait(timeout=timeout)  # Wait for process to terminate
        except subprocess.TimeoutExpired:
            logging.warning(
                f"Process {self.process_id} did not terminate within {timeout} seconds. Killing it."
            )
            self.process.kill()  # Send SIGKILL
        except Exception as e:
            logging.error(f"Error stopping process {self.process_id}: {e}")
        finally:
            self.running = False
            self.returncode = self.process.returncode
            logging.info(f"Process {self.process_id} stopped with return code {self.returncode}")

    def get_status(self) -> dict[str, Any]:
        """Returns the status of the managed process."""
        if self.process:
            if self.running:
                # Double check if the process has exited.  Helpful for unexpected exits.
                if self.process.poll() is not None:
                    self.running = False
                    self.returncode = self.process.returncode
            return {
                "process_id": self.process_id,
                "pid": self.process.pid if self.process else None,
                "running": self.running,
                "returncode": self.returncode,
                "command": self.process_definition.command,
                "env": self.process_definition.env,
                "cwd": self.process_definition.cwd,
            }
        else:
            return {
                "process_id": self.process_id,
                "pid": None,
                "running": False,
                "returncode": None,
                "command": self.process_definition.command,
                "env": self.process_definition.env,
                "cwd": self.process_definition.cwd,
            }

    def read_stdout(self, timeout: float = 0.1) -> str | None:
        """Reads stdout from the process, returns None if no data available within timeout."""
        try:
            return self.stdout_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def read_stderr(self, timeout: float = 0.1) -> str | None:
        """Reads stderr from the process, returns None if no data available within timeout."""
        try:
            return self.stderr_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def send_stdin(self, data: str) -> None:
        """Sends data to the process's stdin."""
        if not self.running or self.process is None or self.process.stdin is None:
            logging.warning(f"Process {self.process_id} is not running or stdin is unavailable.")
            return
        try:
            self.process.stdin.write(data)
            self.process.stdin.flush()
        except Exception as e:
            logging.error(f"Error sending data to process {self.process_id}: {e}")
            if self.process.stdin.closed:
                logging.warning(f"stdin for process {self.process_id} is closed.")

    def _enqueue_output(self, output, queue: queue.Queue):
        """Reads output stream and puts data into the queue."""
        for line in iter(output.readline, ""):
            queue.put(line)
        output.close()


class DockerProcessManager:
    """Manages the lifecycle of multiple processes."""

    def __init__(self, storage_file: str = "process_manager_state.json"):
        self.processes: dict[str, ManagedProcess] = {}
        self.storage_file = storage_file
        self._load_state()  # Load state from file on initialization

    def create_process(self, process_definition: ProcessDefinition) -> str:
        """Creates a new process definition and returns its ID."""
        process_id = str(uuid.uuid4())
        self.processes[process_id] = ManagedProcess(process_id, process_definition)
        self._save_state()
        return process_id

    def start_process(self, process_id: str) -> None:
        """Starts a process by its ID."""
        process = self.get_process(process_id)
        if not process:
            raise ValueError(f"Process with ID {process_id} not found.")

        if process.running:
            logging.warning(f"Process {process_id} is already running.")
            return

        process.start()
        self._save_state()  # Save state after starting
        logging.info(f"Started process: {process_id}")

    def stop_process(self, process_id: str, timeout: float = 10.0) -> None:
        """Stops a process by its ID."""
        process = self.get_process(process_id)
        if not process:
            raise ValueError(f"Process with ID {process_id} not found.")
        process.stop(timeout=timeout)
        self._save_state()  # Save state after stopping
        logging.info(f"Stopped process: {process_id}")

    def get_process(self, process_id: str) -> ManagedProcess | None:
        """Returns a ManagedProcess object by its ID, or None if not found."""
        return self.processes.get(process_id)

    def list_processes(self) -> list[dict[str, Any]]:
        """Lists all managed processes with their status."""
        return [process.get_status() for process in self.processes.values()]

    def update_process(self, process_id: str, new_process_definition: ProcessDefinition) -> None:
        """Updates the definition of a process, but does NOT restart it."""
        process = self.get_process(process_id)
        if not process:
            raise ValueError(f"Process with ID {process_id} not found.")

        # Stop the process if it's running
        if process.running:
            self.stop_process(process_id)

        process.process_definition = new_process_definition
        # Recreate the process but DO NOT start it.
        self.processes[process_id] = ManagedProcess(process_id, new_process_definition)
        self._save_state()
        logging.info(f"Updated process {process_id} (definition only).  Start to apply changes.")

    def delete_process(self, process_id: str) -> None:
        """Deletes a process by its ID."""
        process = self.get_process(process_id)
        # Stop the process if it's running
        if process and process.running:
            self.stop_process(process_id)

        if process_id in self.processes:
            del self.processes[process_id]
            self._save_state()
            logging.info(f"Deleted process: {process_id}")
        else:
            raise ValueError(f"Process with ID {process_id} not found.")

    def send_stdin(self, process_id: str, data: str) -> None:
        """Sends data to the stdin of a process."""
        process = self.get_process(process_id)
        if not process:
            raise ValueError(f"Process with ID {process_id} not found.")
        process.send_stdin(data)

    def read_stdout(self, process_id: str, timeout: float = 0.1) -> str | None:
        """Reads stdout from a process."""
        process = self.get_process(process_id)
        if not process:
            raise ValueError(f"Process with ID {process_id} not found.")
        return process.read_stdout(timeout)

    def read_stderr(self, process_id: str, timeout: float = 0.1) -> str | None:
        """Reads stderr from a process."""
        process = self.get_process(process_id)
        if not process:
            raise ValueError(f"Process with ID {process_id} not found.")
        return process.read_stderr(timeout)

    def _save_state(self) -> None:
        """Saves the current state of the process manager to a file."""
        try:
            data = {
                process_id: process.process_definition.to_dict()
                for process_id, process in self.processes.items()
            }
            with open(self.storage_file, "w") as f:
                json.dump(data, f, indent=4)
            logging.debug(f"State saved to {self.storage_file}")
        except Exception as e:
            logging.error(f"Error saving state to {self.storage_file}: {e}")

    def _load_state(self) -> None:
        """Loads the state of the process manager from a file."""
        try:
            if os.path.exists(self.storage_file):
                with open(self.storage_file) as f:
                    data = json.load(f)
                for process_id, process_data in data.items():
                    try:
                        process_definition = ProcessDefinition.from_dict(process_data)
                        self.processes[process_id] = ManagedProcess(
                            process_id, process_definition
                        )  # DO NOT START
                        logging.debug(f"Loaded process {process_id} from state.")
                    except Exception as e:
                        logging.error(f"Error loading process {process_id} from state: {e}")

                logging.info(f"State loaded from {self.storage_file}")
        except FileNotFoundError:
            logging.warning(
                f"State file {self.storage_file} not found. Starting with an empty state."
            )
        except Exception as e:
            logging.error(f"Error loading state from {self.storage_file}: {e}")

    def shutdown(self):
        """Cleanly shuts down all managed processes. This is important before exiting the application."""
        logging.info("Shutting down DockerProcessManager...")
        for process_id, process in self.processes.items():
            if process.running:
                logging.info(f"Stopping process {process_id} before shutdown.")
                try:
                    process.stop()  # Use the stop method with a timeout
                except Exception as e:
                    logging.error(f"Error stopping process {process_id} during shutdown: {e}")
        logging.info("DockerProcessManager shutdown complete.")


class ProcessManager:
    """Manages CLI application processes asynchronously."""

    def __init__(self):
        self.processes = {}  # {service_name: process}
        self._task_cancel_scope: dict[str, anyio.CancelScope] = {}
        self._task_group = None
        self._lock = anyio.Lock()

    async def start(self) -> None:
        """Starts the process manager."""
        logging.info("Starting process manager...")
        async with self._lock:
            if self._task_group is not None:
                raise RuntimeError("ProcessManager is already started")
            self._task_group = anyio.create_task_group()
            await self._task_group.__aenter__()
            self._task_group.start_soon(self._loop)

    async def stop(self) -> None:
        """Stops the process manager and cancels all processes."""
        logging.info("Stopping process manager...")
        async with self._lock:
            if self._task_group is None:
                return
            self._task_group.cancel_scope.cancel()
            await self._task_group.__aexit__(None, None, None)
            self._task_group = None
            self._task_cancel_scope.clear()

    async def _loop(self):
        try:
            while True:
                # logging.info("Sleeping in the loop...")
                await anyio.sleep(1)
        except BaseException as e:
            logging.exception(e)
            raise

    async def create_process(
        self,
        process_name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        errlog: typing.TextIO = sys.stdout,
    ) -> None:
        """Creates a new process."""
        async with self._lock:
            logging.info("Creating process...")
            if process_name in self._task_cancel_scope:
                raise ValueError(f"Process {process_name} already exists")

            process = await anyio.open_process(
                [command, *args], stdout=sys.stdout, stderr=sys.stdout
            )

            async def task_runner(process) -> None:
                with anyio.CancelScope() as cancel_scope:
                    async with process:
                        self._task_cancel_scope[process_name] = cancel_scope

                # async with anyio.create_task_group() as tg:
                #     try:
                #         tg.start_soon(command_runner)
                #         self._task_cancel_scope[process_name] = tg.cancel_scope
                #         self.processes[process_name] = process
                #         # await process.wait()
                #         await anyio.sleep(15)
                #         logging.info("Trying to cancel directly...")
                #         tg.cancel_scope.cancel()
                #     except BaseException as e:
                #         logging.exception(e)
                #         raise
                #     logging.info("Exited from task runner...")

            self._task_group.start_soon(task_runner, process)

            return process

    async def destroy_process(self, process_name: str) -> None:
        """Destroys a process."""
        logging.info(f"Destroy process called... {self._task_cancel_scope}")
        async with self._lock:
            if process_name not in self._task_cancel_scope:
                logging.error(f"Process {process_name} not found")
                raise ValueError(f"Process {process_name} not found")
            # del self._tasks[task_name]
            try:
                logging.info(f"Process cancel via {self._task_cancel_scope[process_name]}")
                self._task_cancel_scope[process_name].cancel()
            except BaseException as e:
                logging.exception(e)
                raise

    async def start_process(
        self,
        service_name: str,
        command: str,
        args: list[str] | None,
        env: dict[str, str] | None,
        errlog: typing.TextIO = sys.stderr,
    ):
        """Runs a MCP subprocess using anyio, sending text to stdin and capturing text from stdout."""
        logging.info(f"Starting process: {service_name} with command: {command}, args: {args}")

        read_stream: anyio.streams.memory.MemoryObjectReceiveStream[str]
        read_stream_writer: anyio.streams.memory.MemoryObjectSendStream[str]

        write_stream: anyio.streams.memory.MemoryObjectSendStream[str]
        write_stream_reader: anyio.streams.memory.MemoryObjectReceiveStream[str]

        read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
        write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

        # Open process with stderr piped for capture
        process = await anyio.open_process(
            command=command,
            args=args,
            env=env,
            errlog=errlog,
        )

        async with self.lock:
            self.processes[service_name] = process

        async def stdout_reader():
            assert process.stdout, "Opened process is missing stdout"

            try:
                async with read_stream_writer:
                    buffer = ""
                    async for chunk in anyio.streams.text.TextReceiveStream(process.stdout):
                        lines = (buffer + chunk).split("\n")
                        buffer = lines.pop()

                        for line in lines:
                            await read_stream_writer.send(line)
            except anyio.ClosedResourceError:
                await anyio.lowlevel.checkpoint()

        async def stdin_writer():
            assert process.stdin, "Opened process is missing stdin"

            try:
                async with write_stream_reader:
                    async for message in write_stream_reader:
                        await process.stdin.send(message)
            except anyio.ClosedResourceError:
                await anyio.lowlevel.checkpoint()

        async with (
            anyio.create_task_group() as tg,
            process,
        ):
            tg.start_soon(stdout_reader)
            tg.start_soon(stdin_writer)
            try:
                yield read_stream, write_stream
            finally:
                # Clean up process to prevent any dangling orphaned processes
                process.terminate()

        # try:

        #     async with await anyio.open_process('bunx @modelcontextprotocol/inspector', env=env) as process:
        #         async for text in anyio.streams.text.TextReceiveStream(process.stdout):
        #             print(text)

        #     # process = await anyio.create_subprocess_shell(
        #     #     command,
        #     #     stdout=anyio.subprocess.PIPE,
        #     #     stderr=anyio.subprocess.PIPE
        #     # )

        #     async with self.lock:
        #         self.processes[service_name] = process

        #     # Start a task to monitor the process output
        #     # anyio.create_task(self._monitor_process(service_name, process))

        #     logging.info(f"Process {service_name} started with PID: {process.pid}")
        #     return True
        # except Exception as e:
        #     logging.error(f"Error starting process {service_name}: {e}")
        #     return False

    async def stop_process(self, service_name):
        """Stops a CLI application process asynchronously."""
        async with self.lock:
            if service_name in self.processes:
                process = self.processes[service_name]
                logging.info(f"Stopping process: {service_name} (PID: {process.pid})")
                try:
                    process.terminate()  # Or .kill() for a more forceful stop
                    try:
                        await anyio.wait_for(
                            process.wait, timeout=10
                        )  # Wait for graceful termination
                    except anyio.TimeoutError:
                        logging.warning(
                            f"Process {service_name} did not terminate in time, killing it."
                        )
                        process.kill()
                        await process.wait()  # wait for kill
                    del self.processes[service_name]
                    logging.info(f"Process {service_name} stopped.")
                except Exception as e:
                    logging.error(f"Error stopping process {service_name}: {e}")
                return True
            else:
                logging.warning(f"Process {service_name} not found.")
                return False

    async def _monitor_process(self, service_name, process):
        """Monitors the output of a process and logs it asynchronously."""
        while process.returncode is None:  # While the process is running
            try:
                stdout_line = await process.stdout.readline()
                stderr_line = await process.stderr.readline()

                if stdout_line:
                    line = stdout_line.decode("utf-8").strip()
                    logging.info(f"{service_name}: {line}")
                if stderr_line:
                    line = stderr_line.decode("utf-8").strip()
                    logging.error(f"{service_name}: {line}")
            except Exception as e:
                logging.error(f"Error reading output from {service_name}: {e}")
                break
            await anyio.sleep(0.1)  # prevent busy-waiting

        # Process has exited, log the exit code
        return_code = process.returncode
        logging.info(f"Process {service_name} exited with code: {return_code}")

    async def is_running(self, service_name):
        """Checks if a process is currently running asynchronously."""
        async with self.lock:
            if service_name in self.processes:
                return self.processes[service_name].returncode is None
            return False


class ProcessManager_:
    """Manages CLI application processes asynchronously."""

    def __init__(self):
        self.processes = {}  # {service_name: process}
        self.lock = anyio.Lock()

    @contextlib.asynccontextmanager
    async def start_process(
        self,
        service_name: str,
        command: str,
        args: list[str] | None,
        env: dict[str, str] | None,
        errlog: typing.TextIO = sys.stderr,
    ):
        """Runs a MCP subprocess using anyio, sending text to stdin and capturing text from stdout."""
        logging.info(f"Starting process: {service_name} with command: {command}, args: {args}")

        read_stream: anyio.streams.memory.MemoryObjectReceiveStream[str]
        read_stream_writer: anyio.streams.memory.MemoryObjectSendStream[str]

        write_stream: anyio.streams.memory.MemoryObjectSendStream[str]
        write_stream_reader: anyio.streams.memory.MemoryObjectReceiveStream[str]

        read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
        write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

        # Open process with stderr piped for capture
        process = await anyio.open_process(
            command=command,
            args=args,
            env=env,
            errlog=errlog,
        )

        async with self.lock:
            self.processes[service_name] = process

        async def stdout_reader():
            assert process.stdout, "Opened process is missing stdout"

            try:
                async with read_stream_writer:
                    buffer = ""
                    async for chunk in anyio.streams.text.TextReceiveStream(process.stdout):
                        lines = (buffer + chunk).split("\n")
                        buffer = lines.pop()

                        for line in lines:
                            await read_stream_writer.send(line)
            except anyio.ClosedResourceError:
                await anyio.lowlevel.checkpoint()

        async def stdin_writer():
            assert process.stdin, "Opened process is missing stdin"

            try:
                async with write_stream_reader:
                    async for message in write_stream_reader:
                        await process.stdin.send(message)
            except anyio.ClosedResourceError:
                await anyio.lowlevel.checkpoint()

        async with (
            anyio.create_task_group() as tg,
            process,
        ):
            tg.start_soon(stdout_reader)
            tg.start_soon(stdin_writer)
            try:
                yield read_stream, write_stream
            finally:
                # Clean up process to prevent any dangling orphaned processes
                process.terminate()

        # try:

        #     async with await anyio.open_process('bunx @modelcontextprotocol/inspector', env=env) as process:
        #         async for text in anyio.streams.text.TextReceiveStream(process.stdout):
        #             print(text)

        #     # process = await anyio.create_subprocess_shell(
        #     #     command,
        #     #     stdout=anyio.subprocess.PIPE,
        #     #     stderr=anyio.subprocess.PIPE
        #     # )

        #     async with self.lock:
        #         self.processes[service_name] = process

        #     # Start a task to monitor the process output
        #     # anyio.create_task(self._monitor_process(service_name, process))

        #     logging.info(f"Process {service_name} started with PID: {process.pid}")
        #     return True
        # except Exception as e:
        #     logging.error(f"Error starting process {service_name}: {e}")
        #     return False

    async def stop_process(self, service_name):
        """Stops a CLI application process asynchronously."""
        async with self.lock:
            if service_name in self.processes:
                process = self.processes[service_name]
                logging.info(f"Stopping process: {service_name} (PID: {process.pid})")
                try:
                    process.terminate()  # Or .kill() for a more forceful stop
                    try:
                        await anyio.wait_for(
                            process.wait, timeout=10
                        )  # Wait for graceful termination
                    except anyio.TimeoutError:
                        logging.warning(
                            f"Process {service_name} did not terminate in time, killing it."
                        )
                        process.kill()
                        await process.wait()  # wait for kill
                    del self.processes[service_name]
                    logging.info(f"Process {service_name} stopped.")
                except Exception as e:
                    logging.error(f"Error stopping process {service_name}: {e}")
                return True
            else:
                logging.warning(f"Process {service_name} not found.")
                return False

    async def _monitor_process(self, service_name, process):
        """Monitors the output of a process and logs it asynchronously."""
        while process.returncode is None:  # While the process is running
            try:
                stdout_line = await process.stdout.readline()
                stderr_line = await process.stderr.readline()

                if stdout_line:
                    line = stdout_line.decode("utf-8").strip()
                    logging.info(f"{service_name}: {line}")
                if stderr_line:
                    line = stderr_line.decode("utf-8").strip()
                    logging.error(f"{service_name}: {line}")
            except Exception as e:
                logging.error(f"Error reading output from {service_name}: {e}")
                break
            await anyio.sleep(0.1)  # prevent busy-waiting

        # Process has exited, log the exit code
        return_code = process.returncode
        logging.info(f"Process {service_name} exited with code: {return_code}")

    async def is_running(self, service_name):
        """Checks if a process is currently running asynchronously."""
        async with self.lock:
            if service_name in self.processes:
                return self.processes[service_name].returncode is None
            return False


# Example Usage (Illustrative):

if __name__ == "__main__":
    # Example Usage:
    manager = DockerProcessManager("my_processes.json")

    try:
        # 1. Create a process definition (e.g., running 'ping google.com')
        process_definition = ProcessDefinition(
            command=["ping", "google.com"],  # Example: Ping Google
            env={"CUSTOM_VAR": "some_value"},  # Example: Set environment variable
            cwd="/tmp",  # Example: Change the working directory
        )

        # 2. Create the process
        process_id = manager.create_process(process_definition)
        print(f"Created process with ID: {process_id}")

        # 3. Start the process
        manager.start_process(process_id)
        print(f"Started process with ID: {process_id}")

        # 4. Get process status
        status = manager.get_process(
            process_id
        ).get_status()  # access ManagedProcess object thru manager and call get_status() method.
        print(f"Process status: {status}")

        # 5. Read stdout/stderr
        import time

        time.sleep(2)  # Give the process some time to produce output

        stdout_data = manager.read_stdout(process_id)
        if stdout_data:
            print(f"Stdout: {stdout_data.strip()}")

        stderr_data = manager.read_stderr(process_id)
        if stderr_data:
            print(f"Stderr: {stderr_data.strip()}")
        # simulate input
        manager.send_stdin(process_id, "Some input data\n")

        # 6. List all processes
        all_processes = manager.list_processes()
        print(f"All processes: {all_processes}")

        # 7. Update the process definition (e.g., change the command to 'ls -l')
        new_process_definition = ProcessDefinition(
            command=["ls", "-l"],  # Example: Run ls -l
            env={"NEW_VAR": "another_value"},  # Example: Set another environment variable
        )
        manager.update_process(process_id, new_process_definition)
        print(f"Updated process {process_id}.  Start to apply the changes.")

        # To activate changes we shuld start process again.
        manager.start_process(process_id)
        time.sleep(2)  # Give the process some time to produce output

        stdout_data = manager.read_stdout(process_id)
        if stdout_data:
            print(f"Stdout: {stdout_data.strip()}")

        # 8. Stop the process
        manager.stop_process(process_id)
        print(f"Stopped process with ID: {process_id}")

        # 9. Delete the process
        manager.delete_process(process_id)
        print(f"Deleted process with ID: {process_id}")

    except Exception as e:
        print(f"An error occurred: {e}")

    finally:
        manager.shutdown()  # Always call shutdown.
