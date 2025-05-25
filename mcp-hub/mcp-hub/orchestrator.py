import logging

import anyio
import fastmcp
import fastmcp.server

from .config import Config, FileConfigProvider, MCPDockerConfig
from .docker_manager import DockerManager
from .process_manager import ProcessManager

MCP_NETWORK = "mcp-network"


def _config_to_container_kwargs(name: str, mcp_config: MCPDockerConfig):
    return {
        "name": name,
        "image": mcp_config.image,
        "command": mcp_config.command,
        "environment": mcp_config.env,
        "labels": {
            f"traefik.http.middlewares.{name}-stripprefix.stripprefix.prefixes": f"/{name}",
            f"traefik.http.routers.{name}.rule": f"PathPrefix(`/{name}`)",
            f"traefik.http.routers.{name}.middlewares": f"{name}-stripprefix@docker",
            f"traefik.http.services.{name}.loadbalancer.server.port": str(mcp_config.port),
        },
        "network": MCP_NETWORK,
    }


class MCPOrchestrator:
    """Orchestrates MCP services based on a configuration source."""

    def __init__(self, config_source, config_options=None):
        self.config_source = config_source  # 'file', 'database', 'eventbus'
        self.config_options = config_options or {}
        self.process_manager = ProcessManager()
        self.docker_manager = DockerManager()
        self.mcp_servers = {}
        self.lock = anyio.Lock()
        self.config_provider = self._create_config_provider()

    def _create_config_provider(self):
        """Creates the appropriate config provider based on the source."""
        if self.config_source == "file":
            return FileConfigProvider(self.config_options.get("file_path", "mcp_config.yaml"))
        # elif self.config_source == 'database':
        #     return DatabaseConfigProvider(self.config_options)
        # elif self.config_source == 'eventbus':
        #     return EventBusConfigProvider(self.config_options)
        else:
            raise ValueError(f"Invalid configuration source: {self.config_source}")

    def apply_config(self, config: Config):
        """Loads the configuration from the configured provider."""
        if config.mcp_servers:
            self.mcp_servers = config.mcp_servers
            logging.debug("Configuration successfully applied.")
        else:
            logging.warning("No MCP servers configured.")

    async def is_running(self, service_name):
        if service_name not in self.mcp_servers:
            logging.warning(f"Service {service_name} not found in configuration.")
            return False

        service_config = self.mcp_servers[service_name]

        if service_config.type == "cli":
            return await self.process_manager.is_running(service_name)
        if service_config.type == "docker":
            return await self.docker_manager.is_running(service_name)

    async def start_service(self, service_name: str) -> bool:
        """Starts a single MCP service based on its configuration."""
        if service_name not in self.mcp_servers:
            logging.warning(f"Service {service_name} not found in configuration.")
            return False

        service_config = self.mcp_servers[service_name]

        if service_config.type == "cli":
            return await self.process_manager.start_process(
                service_name, service_config.command, service_config.args, service_config.env
            )

        if service_config.type == "docker":
            image = service_config.get("image")
            ports = service_config.get("ports")
            environment = service_config.get("environment")
            network_mode = service_config.get("network_mode")
            if not image:
                logging.error(f"Image missing for Docker service: {service_name}")
                return False
            return await self.docker_manager.start_container(
                service_name, image, ports, environment, network_mode
            )

    async def stop_service(self, service_name: str) -> bool:
        """Stops a single MCP service."""
        if service_name not in self.mcp_servers:
            logging.warning(f"Service {service_name} not found in configuration.")
            return False

        service_config = self.mcp_servers[service_name]

        if service_config.type == "cli":
            return await self.process_manager.stop_process(service_name)
        if service_config.type == "docker":
            return await self.docker_manager.stop_container(service_name)

    async def restart_service(self, service_name):
        """Restarts a single MCP service."""
        logging.info(f"Restarting service: {service_name}")
        if await self.stop_service(service_name):
            await anyio.sleep(2)  # Optional: Wait a short time before restarting
            return await self.start_service(service_name)
        else:
            logging.error(f"Failed to restart service: {service_name}")
            return False

    async def sync_mcp_servers(self):
        """Synchronizes the running services with the configuration source."""
        logging.info("Syncing mcp servers...")
        async with self.lock:
            # Start new services
            for service_name in self.mcp_servers:
                if await self.is_running(service_name):
                    continue
                logging.info(f"Starting {service_name}...")
                await self.start_service(service_name)

            # Stop removed services
            # running_services = set()
            # running_services.update(self.process_manager.processes.keys())
            # running_services.update(self.docker_manager.containers.keys())

            # for service_name in running_services:
            #     if service_name not in self.mcp_servers:
            #         if self.process_manager.is_running(service_name):
            #             logging.info(f"Stopping {service_name} server process...")
            #             self.stop_service(service_name)
            #         elif self.docker_manager.is_running(service_name):
            #             logging.info(f"Stopping {service_name} server Docker container...")
            #             await self.stop_service(service_name)

            # # Check for changes
            # for service_name in self.mcp_servers:
            #     service_config = self.mcp_servers[service_name]
            #     logging.info(f"Configuration Change for {service_name}, restarting... ")
            #     self.restart_service(service_name)

        logging.info("Services synced.")

    async def start_traefik(self): ...

    def _compare_container_states(self, containers, desired):
        for c in containers:
            logging.info(f"asdfadsfasdf {c}")
        current = {c["name"]: c for c in containers}

        to_remove = [name for name in current if name not in desired]
        to_create = []
        to_update = []

        for name, desired_service in desired.items():
            if name not in current:
                to_create.append(name)
                continue

            if self.docker_manager.container_config_changed(
                **_config_to_container_kwargs(name, desired_service)
            ):
                to_update.append(name)

        return to_create, to_update, to_remove

    async def _watch_config(self):
        async for config in self.config_provider.watch():
            logging.info(f"Config reloaded: {config}")

            # todo: add cancel handling and stop process manager and docker manager
            """
            https://anyio.readthedocs.io/en/stable/cancellation.html#finalization
            async def do_something():
                try:
                    await run_async_stuff()
                except get_cancelled_exc_class():
                    # (perform cleanup)
                    raise
                    # Always reraise the cancellation exception if you catch it. Failing to do so may cause undefined behavior in your application.

                    # If you need to use await during finalization, you need to enclose it in a shielded cancel scope, or the operation will be cancelled immediately since it’s in an already cancelled scope:
            """
            async with anyio.create_task_group() as tg:
                containers = self.docker_manager.list_containers()
                to_create, to_update, to_remove = self._compare_container_states(
                    [c for c in containers if c["name"] != "traefik"],
                    {
                        name: s
                        for name, s in config.mcp_servers.items()
                        if isinstance(s, MCPDockerConfig)
                    },
                )

                for name in to_remove:
                    logging.info(f"Removing {name} docker container...")
                    self.docker_manager.stop_container(name)
                    # todo: unmount mcp proxy

                for name in to_create:
                    logging.info(f"Starting {name} docker container...")
                    mcp_config = config.mcp_servers[name]
                    self.docker_manager.start_container(
                        **_config_to_container_kwargs(name, mcp_config)
                    )
                    # todo: mount mcp proxy
                    # check interface type: if port is opened or not etc
                    # tg.start_soon(mount_mcp, "mcp")

                for name in to_update:
                    logging.info(f"Restarting {name} docker container due to config changes...")
                    mcp_config = config.mcp_servers[name]
                    self.docker_manager.stop_container(name)
                    self.docker_manager.start_container(
                        **_config_to_container_kwargs(name, mcp_config)
                    )

                # for name, mcp_config in running_containers.items():
                #     if isinstance(mcp_config, MCPDockerConfig):
                #         if name not in config.mcp_servers:
                #             logging.info(f"Stopping {name} docker container...")
                #             self.docker_manager.stop_container(name)
                #             # todo: unmount mcp proxy

                #     if isinstance(mcp_config, MCPCliConfig):
                #         ...

                # for name, mcp_config in config.mcp_servers.items():
                #     if isinstance(mcp_config, MCPDockerConfig):

                #         def start_container(name, mcp_config):
                #             return self.docker_manager.start_container(
                #                 **_config_to_container_kwargs(name, mcp_config)
                #             )

                #         if name not in running_containers:
                #             logging.info(f"Starting {name} docker container...")
                #             start_container(name, mcp_config)
                #             running_containers[name] = mcp_config
                #             # todo: mount mcp proxy
                #             # check interface type: if port is opened or not etc
                #             # tg.start_soon(mount_mcp, "mcp")
                #         else:
                #             # todo: check if need restart
                #             logging.info(f"Restarting {name} docker container...")
                #             self.docker_manager.stop_container(name)
                #             start_container(name, mcp_config)

                #     if isinstance(mcp_config, MCPCliConfig):
                #         ...

                # todo: check if it is already running

                # process = await self.process_manager.create_process(
                #     name, mcp_server.command, mcp_server.args, mcp_server.env
                # )

                # logging.info(f"Process is {process}")

                # container = self.docker_manager.start_container(mcp_server)

                # async def run_stdio_mcp_proxy(name, stdin, stdout):
                #     # todo: add sse transport detection
                #     transport = StdioTransport(stdin, stdout)  # fixme
                #     proxy = fastmcp.FastMCP.from_client(fastmcp.Client(transport))
                #     main_mcp.mount(name, proxy)

            # added servers

            # await self.apply_config(config)
            # await self.sync_mcp_servers()
            # await self.sync_mcp_servers()

    async def start(self):
        """Runs the orchestrator and monitoring for configuration changes."""
        # self.sync_mcp_servers()  # Initial sync

        # try:
        #     self.config_provider.start_watching(self.load_config, self.sync_mcp_servers) # Add sync_services as callback
        #     while True:
        #         time.sleep(60)  # Main loop.  Let the ConfigProvider handle changes.
        # except KeyboardInterrupt:
        #     logging.info("Stopping the MCP orchestrator...")
        # finally:
        #     self.config_provider.stop_watching()

        # async with anyio.create_task_group() as tg:

        # while config_changes:
        #     if add_service:
        #         mcp mount <- start_service()
        #     if remove_service:
        #         mcp unmount <- stop_service()

        try:
            await self.process_manager.start()
            main_mcp = fastmcp.FastMCP(name="MCPHub")

            network = self.docker_manager.create_network(
                MCP_NETWORK
            ) or self.docker_manager.get_network(MCP_NETWORK)
            self.docker_manager.start_container(
                "traefik",
                "traefik:v3",
                ["--api.insecure=true", "--providers.docker"],
                ports={"8080/tcp": 8080, "80/tcp": 80, "9191/tcp": 1881},
                volumes={"/var/run/docker.sock": {"bind": "/var/run/docker.sock"}},
                network=MCP_NETWORK,
            )
            await self._watch_config()
        except anyio.get_cancelled_exc_class():
            logging.info("Stopping mcp orchestrator...")
            with anyio.CancelScope(shield=True):
                # await self._stop_processes()
                ...
            logging.info(f"KEYS {','.join(self.docker_manager.containers.keys())}")
            containers = list(self.docker_manager.containers.keys())
            for container in containers:
                self.docker_manager.stop_container(container)
            self.docker_manager.stop_container("traefik")
            if network:
                self.docker_manager.remove_network(network.id)
            raise

        async def mount_mcp(name):
            logging.info(f"Mounting docker api as {name}")
            main_mcp.mount(name, fastmcp.FastMCP.as_proxy)
