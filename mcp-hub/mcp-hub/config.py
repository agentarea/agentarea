import logging
from collections.abc import AsyncIterable
from typing import Annotated, Literal

import anyio
import pydantic
import watchfiles
import yaml


class MCPDockerConfig(pydantic.BaseModel):
    type: Literal["docker"]
    image: str
    command: str | None = None
    port: int
    secrets: dict[str, str] | None = None
    env: dict[str, str] | None = None
    model_config = pydantic.ConfigDict(extra="forbid")


class MCPCliConfig(pydantic.BaseModel):
    type: Literal["cli"]
    command: str
    args: list[str]
    env: dict[str, str] | None = None
    model_config = pydantic.ConfigDict(extra="forbid")


MCPConfig = Annotated[
    MCPDockerConfig | MCPCliConfig, pydantic.Field(discriminator="type")
]


class Config(pydantic.BaseModel):
    mcp_servers: dict[str, MCPConfig] = pydantic.Field([], alias="mcp-servers")
    model_config = pydantic.ConfigDict(validate_by_name=True)


class ConfigProvider:
    """Abstract base class for configuration providers."""

    def __init__(self):
        pass

    async def load_config(self) -> Config:
        """Loads the configuration."""
        raise NotImplementedError

    async def watch(self) -> Config:
        """Watches the configuration."""
        raise NotImplementedError


class FileConfigProvider(ConfigProvider):
    """Loads configuration from a YAML file and watches for changes."""

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path

    async def load_config(self):
        """Loads the configuration from the YAML file."""
        # raw_config = yaml.safe_load(content)
        # return Config.model_validate(raw_config)

        try:
            content = await anyio.Path(self.file_path).read_text()
            raw_config = yaml.safe_load(content)
            return Config(**raw_config)
        except FileNotFoundError:
            logging.error(f"Configuration file not found: {self.file_path}")
            raise
        except yaml.YAMLError as e:
            logging.error(f"Error parsing configuration file: {e}")
            raise

    async def watch(self) -> AsyncIterable[Config]:  # Add sync_services_callback
        """Starts watching for changes to the configuration file."""
        last_valid_config: Config | None = None
        try:
            # Load initial config
            last_valid_config = await self.load_config()
            yield last_valid_config
        except pydantic.ValidationError as e:
            logging.error(f"Invalid config {e.errors()}", exc_info=e)
        except (yaml.YAMLError, FileNotFoundError) as e:
            logging.error(f"Initial config could not be loaded: {e}", exc_info=e)

        async for _ in watchfiles.awatch(self.file_path):
            try:
                new_config = await self.load_config()
                if last_valid_config != new_config:
                    last_valid_config = new_config
                    yield new_config
            except (pydantic.ValidationError, yaml.YAMLError, FileNotFoundError) as e:
                print(f"Could not load config after changes: {e}")
                continue


# class DatabaseConfigProvider(ConfigProvider):
#     """Loads configuration from a PostgreSQL database and polls for changes."""

#     def __init__(self, db_options):
#         super().__init__()
#         self.db_options = db_options
#         self.conn = None  # Database connection
#         self.cursor = None # Database cursor
#         self.polling_interval = self.db_options.get('polling_interval', 60)  # seconds
#         self.watching_thread = None
#         # Initialize the connection
#         try:
#             # Create a connection to the database
#             self.conn = psycopg.connect(**self.db_options)
#             self.cursor = self.conn.cursor()
#             logging.info("Connected to the database.")
#         except psycopg.Error as e:
#             logging.error(f"Failed to connect to the database: {e}")
#             raise  # Re-raise to prevent the orchestrator from starting

#     def load_config(self):
#         """Loads the configuration from the database."""
#         try:
#             # Execute a query to retrieve the service configurations.
#             # Adapt the query and table/column names to your database schema.
#             self.cursor.execute("SELECT config_data FROM mcp_config WHERE config_name = 'services'")
#             result = self.cursor.fetchone()
#             if result:
#                 config_data = result[0]
#                 # Assuming config_data is stored as JSON in the database
#                 return json.loads(config_data)
#             else:
#                 logging.warning("No configuration found in the database.")
#                 return None
#         except psycopg.Error as e:
#             logging.error(f"Error loading configuration from the database: {e}")
#             return None

#     def start_watching(self, load_config_callback, sync_services_callback):
#         """Starts polling the database for changes.
#            Uses modified_at column, so the record in database must have this column.
#         """
#         self.last_modified = None  # Initialize last modified timestamp

#         def watch_loop():
#             logging.info("Starting database watch loop...")
#             while self.watching_thread_running:
#                 try:
#                     self.cursor.execute("SELECT config_data, modified_at FROM mcp_config WHERE config_name = 'services'")
#                     result = self.cursor.fetchone()
#                     if result:
#                         config_data, modified_at = result
#                         if self.last_modified is None or modified_at > self.last_modified:
#                             logging.info("Database configuration changed. Reloading...")
#                             self.last_modified = modified_at
#                             load_config_callback()
#                             sync_services_callback() # Call sync_services after loading config
#                         else:
#                             logging.debug("Database config unchanged.") # Log Debug

#                     else:
#                         logging.warning("No configuration found in the database.")

#                     time.sleep(self.polling_interval)

#                 except psycopg.Error as e:
#                     logging.error(f"Error while polling the database: {e}")
#                     time.sleep(self.polling_interval * 2)  # Wait longer on error
#                 except Exception as e:
#                     logging.error(f"Unexpected error in database watch loop: {e}")
#                     time.sleep(self.polling_interval * 2)

#         self.watching_thread_running = True
#         self.watching_thread = threading.Thread(target=watch_loop, daemon=True)
#         self.watching_thread.start()


#     def stop_watching(self):
#         """Stops polling the database for changes."""
#         if self.watching_thread:
#             self.watching_thread_running = False  # Signal thread to stop
#             self.watching_thread.join()
#             logging.info("Database watch loop stopped.")
#         if self.cursor:
#             self.cursor.close()
#         if self.conn:
#             self.conn.close()
#             logging.info("Database connection closed.")

# class EventBusConfigProvider(ConfigProvider):
#     """Loads configuration from an event bus (Redis Pub/Sub) and updates on events."""

#     def __init__(self, bus_options):
#         super().__init__()
#         self.bus_options = bus_options
#         self.redis_client = None
#         self.pubsub = None
#         self.channel = self.bus_options.get('channel', 'mcp_config_updates')
#         self.watching_thread = None

#         # Initialize the Redis client
#         try:
#             self.redis_client = redis.Redis(**self.bus_options)
#             self.pubsub = self.redis_client.pubsub()
#             logging.info("Connected to Redis.")
#         except redis.exceptions.ConnectionError as e:
#             logging.error(f"Failed to connect to Redis: {e}")
#             raise  # Re-raise to prevent the orchestrator from starting

#     def load_config(self):
#         """Loads the configuration from Redis (if available as a key)."""
#         try:
#             config_data = self.redis_client.get('mcp_config:services')  # Fetch from direct key (Optional)
#             if config_data:
#                 logging.info("Config Loaded from Redis Key")
#                 return json.loads(config_data.decode('utf-8'))

#             logging.warning("No initial config in Redis Key. Using last version or waiting update from channel...")
#             return self.latest_config if hasattr(self, 'latest_config') else {} # Return the cached or empty Dictionary

#         except redis.exceptions.RedisError as e:
#             logging.error(f"Error loading config from Redis key: {e}")
#             return None

#     def start_watching(self, load_config_callback, sync_services_callback):
#         """Subscribes to the Redis channel and updates configuration on messages."""

#         def message_handler(message):
#             if message['type'] == 'message':
#                 try:
#                     config_data = json.loads(message['data'].decode('utf-8'))
#                     logging.info("Received configuration update from Redis channel.")
#                     self.latest_config = config_data  # Cache the latest config
#                     load_config_callback()
#                     sync_services_callback()  # Sync after loading

#                 except json.JSONDecodeError as e:
#                     logging.error(f"Error decoding JSON from Redis message: {e}")
#                 except Exception as e:
#                      logging.error(f"Error processing redis message: {e}")

#         def pubsub_loop():
#           try:
#             logging.info(f"Subscribing to Redis channel: {self.channel}")
#             self.pubsub.subscribe(**{self.channel: message_handler})
#             self.pubsub.run_in_thread(sleep_time=0.1)  # Adjust sleep time as needed
#           except Exception as e:
#               logging.error(f"Exception in redis loop: {e}")

#         self.watching_thread = threading.Thread(target=pubsub_loop, daemon=True)
#         self.watching_thread.start()

#     def stop_watching(self):
#         """Unsubscribes from the Redis channel."""
#         if self.watching_thread:
#             try:
#                 self.pubsub.unsubscribe(self.channel)
#                 logging.info(f"Unsubscribed from Redis channel: {self.channel}")
#             except Exception as e:
#                 logging.error(f"Error unsubscribing from Redis channel: {e}")

#             # Give thread time to stop
#             self.watching_thread.join(timeout=5)

#             # Check if the thread terminated
#             if self.watching_thread.is_alive():
#                 logging.warning("Redis thread did not terminate in time")
#         if self.redis_client:
#             try:
#                 self.redis_client.close()
#                 logging.info("Redis client connection closed.")
#             except Exception as e:
#                 logging.error(f"Error Closing Redis connection: {e}")


# Example usage:

# 1. File-based configuration
# config_source = "file"
# config_options = {"file_path": "mcp_config.yaml"}

# 2. Database-based configuration (PostgreSQL)
# config_source = "database"
# config_options = {
#     "dbname": "your_db_name",
#     "user": "your_user",
#     "password": "your_password",
#     "host": "localhost",
#     "port": 5432,
#     "polling_interval": 30,
# }

# 3. Event Bus configuration (Redis Pub/Sub)
# config_source = "eventbus"
# config_options = {
#     "host": "localhost",
#     "port": 6379,
#     "db": 0,
#     "channel": "mcp_config_updates"
# }
