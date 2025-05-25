import io
import logging
import threading
from pprint import pformat

import docker

# Configure the logger
logging.basicConfig(
    level=logging.INFO,  # Or logging.DEBUG for more detailed output
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

MCP_HUB_MANAGED_LABEL = "mcphub._managed"


def _command_changed(docker_cmd: list[str] | None, config_command: str | list[str] | None):
    if config_command is None:
        return False
    if isinstance(config_command, str):
        return docker_cmd == config_command.split()
    return docker_cmd == config_command


def _ports_changed(
    docker_ports: dict[str, int | list[int] | tuple[str, int] | None],
    config_ports: dict[str, int | list[int] | tuple[str, int] | None] | None,
):
    if config_ports is None:
        return False
    for port, host_port in config_ports:
        if docker_ports[port] != host_port:
            return True
    return False


def _env_changed(
    docker_env: dict[str, str] | list[str],
    config_env: dict[str, str] | list[str] | None,
):
    if config_env is None:
        return False
    de = docker_env if isinstance(docker_env, list) else [f"{k}={v}" for k, v in docker_env.items()]
    ce = config_env if isinstance(config_env, list) else [f"{k}={v}" for k, v in config_env.items()]
    return de != ce


def _network_changed(docker_networks: dict, config_network: str | None):
    return config_network is not None and config_network not in docker_networks


def _labels_changed(
    docker_labels: dict[str, str], config_labels: dict[str, str] | list[str] | None
):
    if config_labels is None:
        return False
    dl = (
        docker_labels
        if isinstance(docker_labels, list)
        else [f"{k}={v}" for k, v in docker_labels.items()]
    )
    cl = (
        config_labels
        if isinstance(config_labels, list)
        else [f"{k}={v}" for k, v in config_labels.items()]
    )
    return dl != cl


def _volumes_changed(
    docker_volumes: dict[str, str], config_volumes: dict[str, dict[str, str]] | list[str] | None
):
    if config_volumes is None:
        return False
    dv = (
        docker_volumes
        if isinstance(docker_volumes, list)
        else [f"{k}:{v['bind']}:{v['mode']}" for k, v in docker_volumes.items()]
    )
    cv = (
        config_volumes
        if isinstance(config_volumes, list)
        else [f"{k}:{v['bind']}:{v['mode']}" for k, v in config_volumes.items()]
    )
    return dv != cv


class DockerManager:
    """Manages Docker container instances."""

    def __init__(self):
        """Initializes the Docker client."""
        self.lock = threading.Lock()
        self.client = docker.from_env()
        self.refresh_containers()

    def start_container(
        self,
        name: str,
        image: str,
        command: str | list[str] | None = None,
        *,
        ports: dict[str, int | list[int] | tuple[str, int] | None] | None = None,
        environment: dict[str, str] | list[str] | None = None,
        network_mode: str | None = None,
        network: str | None = None,
        volumes: dict[str, dict[str, str]] | list[str] | None = None,
        labels: dict[str, str] | list[str] | None = None,
    ):
        """Starts a Docker container.

        Args:
            name (str): The name of the container.
            image (str): The Docker image to use.
            command (str | list[str] | None): The command to run in the container.
            ports (dict[str, int | list[int] | tuple[str, int] | None] | None): Ports to expose.
            environment (dict[str, str] | list[str] | None): Environment variables.
            network_mode (str | None): Network mode for the container.
            network (str | None): Network to connect the container to.
            volumes (dict[str, dict[str, str]] | list[str] | None): Volumes to mount.
            labels (dict[str, str] | list[str] | None): Labels to apply to the container.
        """
        if labels is None:
            labels = {}
        if isinstance(labels, dict):
            labels[MCP_HUB_MANAGED_LABEL] = "1"
        else:
            labels.append(f"{MCP_HUB_MANAGED_LABEL}=1")
        try:
            logger.info(f"Starting container: {name} from image: {image}")
            container = self.client.containers.run(
                image,
                command,
                name=name,
                ports=ports,  # Example: {'80/tcp': 8080}
                environment=environment,  # Example: {'VAR1': 'value1'}
                detach=True,  # Run in detached mode
                network_mode=network_mode,  # Example: 'host' or 'bridge' or name of network
                network=network,
                volumes=volumes,
                labels=labels,
            )
            with self.lock:
                self.containers[name] = container
            logger.info(f"Container {name} started with ID: {container.id}")
            return container
        except docker.errors.ImageNotFound:
            logger.error(f"Image {image} not found for service {name}.")
            return False
        except docker.errors.APIError as e:
            logger.error(f"Error starting container {name}: {e}", exc_info=True)
            return False
        except Exception:
            logger.error(f"Generic error for container {name}", exc_info=True)
            return False

    def refresh_containers(self):
        """Refreshes the list of managed containers."""
        self.containers = {}
        filters = {"label": MCP_HUB_MANAGED_LABEL}
        for container in self.client.containers.list(filters=filters):
            self.containers[container.name] = container

    def list_containers(self):
        """Lists all running containers with basic information."""
        self.refresh_containers()
        containers = []
        for container in self.containers.values():
            logger.info(f"Container from docker: {pformat(container.attrs)}")
            containers.append(
                {
                    "id": container.id,
                    "name": container.name,
                    "status": container.status,
                }
            )
        return containers

    def container_config_changed(
        self,
        name: str,
        image: str,
        command: str | list[str] | None = None,
        *,
        ports: dict[str, int | list[int] | tuple[str, int] | None] | None = None,
        environment: dict[str, str] | list[str] | None = None,
        network_mode: str | None = None,
        network: str | None = None,
        volumes: dict[str, dict[str, str]] | list[str] | None = None,
        labels: dict[str, str] | list[str] | None = None,
    ):
        container = self.containers[name]
        if not container:
            # raise exception instead
            return None

        ctnr_env = dict(e.split("=", 1) for e in container.attrs["Config"]["Env"])
        ctnr_volumes = container.attrs["Config"]["Volumes"]
        ctnr_networks = container.attrs["NetworkSettings"]["Networks"]

        return (
            image != container.image
            or _command_changed(container.command, command)
            or _ports_changed(container.ports, ports)
            or _env_changed(ctnr_env, environment)
            or _network_changed(ctnr_networks, network)
            or _labels_changed(container.labels, labels)
            or _volumes_changed(ctnr_volumes, volumes)
        )

    def stop_container(self, service_name):
        """Stops a Docker container."""
        with self.lock:
            if service_name in self.containers:
                container = self.containers[service_name]
                logging.info(f"Stopping container: {service_name} (ID: {container.id})")
                try:
                    container.stop(timeout=10)  # Graceful stop
                    container.remove()
                    del self.containers[service_name]
                    logging.info(f"Container {service_name} stopped and removed.")
                except docker.errors.APIError as e:
                    logging.error(f"Error stopping container {service_name}", exc_info=e)
                except Exception as e:
                    logging.error(f"Generic error stopping container {service_name}", exc_info=e)
                return True
            else:
                logger.warning(f"Container {service_name} not found.")
            return False

    def is_running(self, service_name):
        """Checks if a container is currently running."""
        with self.lock:
            if service_name in self.containers:
                try:
                    container = self.client.containers.get(service_name)
                    container.reload()
                    return container.status == "running"
                except docker.errors.NotFound:
                    return False
                except Exception as e:
                    logging.error(f"Error checking the container {service_name}: {e}")
                    return False
            return False

    def create_network(self, name):
        try:
            logging.info(f"Creating network: {name}")
            network = self.client.networks.create(name)
            logging.info(f"Network {name} created with ID: {network.id}")
            return network
        except docker.errors.APIError as e:
            logging.error(f"Error creating network {name}: {e}")
            return False
        except Exception as e:
            logging.error(f"Unknown error while creating of network {name}: {e}")
            return False

    def get_network(self, name):
        networks = self.client.networks.list([name])
        if len(networks) == 1:
            return networks[0]
        return None

    def remove_network(self, network_id):
        logging.info(f"Deleting network: {network_id}")
        try:
            network = self.client.networks.get(network_id)
            network.remove()
        except docker.errors.NotFound as e:
            raise ValueError(f"Network {network_id} not found") from e
        except docker.errors.APIError as e:
            raise RuntimeError(f"Failed to remove network: {str(e)}") from e


class DockerManager2:
    """Manages Docker containers."""

    def __init__(self):
        """Initializes the Docker client."""
        try:
            self.client = docker.from_env()
            self.containers = {}  # Store containers by ID for easier management
            self.refresh_containers()  # Load initial container list
            logger.info("Docker client connected successfully.")
        except docker.errors.DockerException as e:
            logger.error(
                f"Error connecting to Docker daemon: {e}", exc_info=True
            )  # Log the exception traceback
            self.client = None
            self.containers = {}

    def refresh_containers(self):
        """Refreshes the list of managed containers."""
        if not self.client:
            logger.warning("Docker client not initialized.  Cannot refresh containers.")
            return

        self.containers = {}
        for container in self.client.containers.list():
            self.containers[container.id] = container

    def list_containers(self):
        """Lists all running containers with basic information."""
        self.refresh_containers()  # Ensure the container list is up-to-date

        if not self.containers:
            logger.info("No containers are currently running.")
            return []

        container_list = []
        for container_id, container in self.containers.items():
            container_list.append(
                {
                    "id": container.id,
                    "name": container.name,
                    "status": container.status,
                    "image": container.image.tags[0]
                    if container.image.tags
                    else "No tag",  # Handle untagged images
                }
            )
        return container_list

    def start_container(self, container_id):
        """Starts a container.

        Args:
            container_id (str): The ID of the container to start.
        """
        self.refresh_containers()

        if not self.client:
            logger.warning("Docker client not initialized.  Cannot start containers.")
            return

        if container_id not in self.containers:
            logger.error(f"Container with ID '{container_id}' not found.")
            return False

        try:
            container = self.containers[container_id]
            container.start()
            self.refresh_containers()  # update list
            logger.info(f"Container '{container.name}' (ID: {container.id}) started successfully.")
            return True
        except docker.errors.APIError as e:
            logger.error(
                f"Error starting container '{container_id}': {e}", exc_info=True
            )  # Log with traceback
            return False

    def stop_container(self, container_id):
        """Stops a container.

        Args:
            container_id (str): The ID of the container to stop.
        """
        self.refresh_containers()

        if not self.client:
            logger.warning("Docker client not initialized.  Cannot stop containers.")
            return

        if container_id not in self.containers:
            logger.error(f"Container with ID '{container_id}' not found.")
            return False

        try:
            container = self.containers[container_id]
            container.stop()
            self.refresh_containers()  # update list
            logger.info(f"Container '{container.name}' (ID: {container.id}) stopped successfully.")
            return True
        except docker.errors.APIError as e:
            logger.error(
                f"Error stopping container '{container_id}': {e}", exc_info=True
            )  # Log with traceback
            return False

    def get_container_info(self, container_id):
        """Gets detailed information about a container.

        Args:
            container_id (str): The ID of the container.

        Returns:
            dict: A dictionary containing container information, or None if the
                  container is not found.
        """
        self.refresh_containers()

        if not self.client:
            logger.warning("Docker client not initialized.  Cannot get container info.")
            return None

        if container_id not in self.containers:
            logger.error(f"Container with ID '{container_id}' not found.")
            return None

        try:
            container = self.containers[container_id]
            info = container.attrs  # get all container attributes
            # Optionally:  Filter, format, or pretty-print the 'info' dict
            # For example, to print as JSON:
            # print(json.dumps(info, indent=4))

            return info
        except docker.errors.APIError as e:
            logger.error(
                f"Error getting info for container '{container_id}': {e}", exc_info=True
            )  # Log with traceback
            return None

    def create_container(
        self,
        image,
        command=None,
        ports=None,
        volumes=None,
        environment=None,
        name=None,
        detach=True,
    ):
        """Creates a new container from an image.

        Args:
            image (str): The name of the Docker image.
            command (str, list): The command to run in the container. Defaults to None.
            ports (dict):  A dictionary mapping container ports to host ports. Defaults to None. e.g., {'80/tcp': 8080}
            volumes (dict): A dictionary mapping host paths to container paths.  Defaults to None. e.g., {'/host/path': {'bind': '/container/path', 'mode': 'rw'}}
            environment (dict, list): A dictionary or list of strings defining environment variables. Defaults to None.
            name (str): The name of the container. Defaults to None.
            detach (bool): Run container in the background. Defaults to True.

        Returns:
            str: The ID of the created container, or None if creation failed.
        """
        if not self.client:
            logger.warning("Docker client not initialized. Cannot create containers.")
            return None

        try:
            container = self.client.containers.create(
                image=image,
                command=command,
                ports=ports,
                volumes=volumes,
                environment=environment,
                name=name,
                detach=detach,
            )
            self.refresh_containers()  # Update container list
            logger.info(f"Container '{container.name}' (ID: {container.id}) created successfully.")
            return container.id
        except docker.errors.ImageNotFound as e:
            logger.error(f"Image not found: {e}", exc_info=True)  # Log with traceback
            return None
        except docker.errors.APIError as e:
            logger.error(f"Error creating container: {e}", exc_info=True)  # Log with traceback
            return None

    def remove_container(self, container_id, force=False):
        """Removes a container.

        Args:
            container_id (str): The ID of the container to remove.
            force (bool, optional): Whether to force remove the container if it's running. Defaults to False.

        Returns:
            bool: True if the container was successfully removed, False otherwise.
        """
        self.refresh_containers()

        if not self.client:
            logger.warning("Docker client not initialized. Cannot remove containers.")
            return False

        if container_id not in self.containers:
            logger.error(f"Container with ID '{container_id}' not found.")
            return False

        try:
            container = self.containers[container_id]
            container.remove(force=force)
            self.refresh_containers()  # Update the container list
            logger.info(f"Container '{container.name}' (ID: {container.id}) removed successfully.")
            return True
        except docker.errors.APIError as e:
            logger.error(
                f"Error removing container '{container_id}': {e}", exc_info=True
            )  # Log with traceback
            return False  # Or handle specific exceptions like ContainerNotRunning, etc.

    def attach_to_container(self, container_id):
        """Attaches to a container's stdin and stdout.
        This function starts a blocking connection to the container's streams.

        Args:
            container_id (str): The ID of the container to attach to.
        """
        self.refresh_containers()

        if not self.client:
            logger.warning("Docker client not initialized. Cannot attach to containers.")
            return

        if container_id not in self.containers:
            logger.error(f"Container with ID '{container_id}' not found.")
            return

        try:
            container = self.containers[container_id]

            # Get the socket object for attaching
            socket = container.attach_socket(
                params={"stdin": True, "stdout": True, "stream": True, "detachKeys": "ctrl-c"}
            )

            # Function to read from the socket and print to the console
            def read_socket(socket):
                try:
                    while True:
                        data = socket.read(1)  # Read one byte at a time
                        if data:
                            print(
                                data.decode("utf-8", errors="ignore"), end="", flush=True
                            )  # Print to stdout
                        else:
                            break  # Socket closed
                except Exception as e:
                    logger.error(f"Error reading from socket: {e}", exc_info=True)

            # Function to write from stdin to the socket
            def write_socket(socket):
                try:
                    while True:
                        try:  # Catch io exceptions due to abrupt exit
                            input_data = input() + "\n"
                            socket.write(input_data.encode("utf-8"))
                        except EOFError:
                            logger.info("EOFError: stdin closed.")
                            break  # Exit the loop on EOF (Ctrl+D)
                        except io.UnsupportedOperation:
                            logger.info("io.UnsupportedOperation: stdin closed or detached")
                            break
                except Exception as e:
                    logger.error(f"Error writing to socket: {e}", exc_info=True)

            # Start threads for reading and writing to the socket
            read_thread = threading.Thread(target=read_socket, args=(socket,))
            write_thread = threading.Thread(target=write_socket, args=(socket,))

            read_thread.daemon = (
                True  # Allow the main thread to exit even if the read thread is running
            )
            write_thread.daemon = True  # Allow the main thread to exit.

            read_thread.start()
            write_thread.start()

            # Wait for threads to finish.  In reality they will detach with Ctrl+C
            read_thread.join()
            write_thread.join()

            # Cleanup
            socket.close()
            logger.info(f"Detached from container '{container.name}' (ID: {container.id}).")

        except docker.errors.APIError as e:
            logger.error(f"Error attaching to container '{container_id}': {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Unexpected error attaching to container: {e}", exc_info=True)
