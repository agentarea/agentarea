"""MCP configuration validation service."""

import asyncio
import logging
from typing import Any
from urllib.parse import urljoin

import httpx

logger = logging.getLogger(__name__)


class MCPValidationError(Exception):
    """Custom validation error for MCP configurations."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"Validation failed: {'; '.join(errors)}")


class MCPConfigurationValidator:
    """Validates MCP instance configurations."""

    # Configuration for the golang MCP manager
    MCP_MANAGER_BASE_URL = "http://mcp-manager"  # Use service name for Docker networking
    MCP_MANAGER_TIMEOUT = 30.0  # seconds

    @staticmethod
    def validate_json_spec(json_spec: dict[str, Any]) -> list[str]:
        """Validate a JSON specification for MCP instance creation.

        Args:
            json_spec: The JSON specification to validate

        Returns:
            List of validation error messages (empty if valid)
        """
        errors: list[str] = []

        # Required fields
        required_fields = ["image", "port"]
        for field in required_fields:
            if field not in json_spec:
                errors.append(f"Required field '{field}' is missing")

        # Validate image field
        if "image" in json_spec:
            image = json_spec["image"]
            if not isinstance(image, str) or not image.strip():
                errors.append("Field 'image' must be a non-empty string")

        # Validate port field
        if "port" in json_spec:
            port = json_spec["port"]
            if not isinstance(port, int) or port < 1 or port > 65535:
                errors.append("Field 'port' must be an integer between 1 and 65535")

        # Validate environment variables if present
        if "environment" in json_spec:
            env_vars = json_spec["environment"]
            if not isinstance(env_vars, dict):
                errors.append("Field 'environment' must be a dictionary")
            else:
                for key, value in env_vars.items():
                    if not isinstance(key, str) or not key.strip():
                        errors.append(
                            f"Environment variable key '{key}' must be a non-empty string"
                        )
                    if not isinstance(value, str):
                        errors.append(f"Environment variable '{key}' value must be a string")

        # Validate command if present
        if "cmd" in json_spec:
            cmd = json_spec["cmd"]
            if cmd is not None:
                if not isinstance(cmd, list):
                    errors.append("Field 'cmd' must be a list of strings")
                else:
                    for i, item in enumerate(cmd):
                        if not isinstance(item, str):
                            errors.append(f"Command item at index {i} must be a string")

        return errors

    @classmethod
    async def validate_with_golang_manager(
        cls,
        json_spec: dict[str, Any],
        instance_id: str = "validation-check",
        name: str = "validation-check",
    ) -> list[str]:
        """Validate configuration using the golang MCP manager.

        Args:
            json_spec: The JSON specification to validate
            instance_id: Instance ID for validation
            name: Service name for validation

        Returns:
            List of validation error messages (empty if valid)
        """
        errors: list[str] = []

        try:
            # Make request to golang validation endpoint
            async with httpx.AsyncClient(timeout=cls.MCP_MANAGER_TIMEOUT) as client:
                validation_url = urljoin(cls.MCP_MANAGER_BASE_URL, "/containers/validate")

                validation_payload = {
                    "instance_id": instance_id,
                    "name": name,
                    "json_spec": json_spec,
                    "dry_run": True,
                }

                logger.info(f"Validating configuration with golang manager: {validation_url}")

                try:
                    response = await client.post(validation_url, json=validation_payload)

                    if response.status_code == 200:
                        validation_result = response.json()

                        # Check if validation passed
                        if not validation_result.get("valid", False):
                            errors.extend(validation_result.get("errors", []))

                        # Add warnings as info (not errors)
                        warnings = validation_result.get("warnings", [])
                        if warnings:
                            logger.info(f"Validation warnings: {warnings}")

                    else:
                        # Handle error response
                        try:
                            error_data = response.json()
                            error_message = error_data.get(
                                "message", f"Validation failed with status {response.status_code}"
                            )
                            errors.append(f"Container validation failed: {error_message}")
                        except Exception:
                            errors.append(f"Validation failed with status {response.status_code}")

                except httpx.ConnectError:
                    # If golang manager is not available, log warning but continue with basic validation
                    logger.warning(
                        "Golang MCP manager not available for validation, using basic validation only"
                    )

                except httpx.TimeoutException:
                    logger.warning(
                        "Golang MCP manager validation timed out, using basic validation only"
                    )

                except Exception as e:
                    logger.error(f"Error during golang manager validation: {e}")

        except Exception as e:
            logger.error(f"Failed to validate with golang manager: {e}")
            # Don't add error here - we'll fall back to basic validation

        return errors

    @classmethod
    async def validate_full_configuration_async(
        cls, json_spec: dict[str, Any], provider_schema: dict[str, Any] | None = None
    ) -> list[str]:
        """Perform complete async validation of MCP configuration.

        Args:
            json_spec: The JSON specification to validate
            provider_schema: Optional provider schema for additional validation

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Basic structure validation
        errors.extend(cls.validate_json_spec(json_spec))

        # Only proceed with golang validation if basic validation passes
        if not errors:
            # Validate with golang manager
            golang_errors = await cls.validate_with_golang_manager(json_spec)
            errors.extend(golang_errors)

        # Provider-specific validation if schema provided
        if provider_schema is not None and not errors:
            errors.extend(cls.validate_against_provider_schema(json_spec, provider_schema))

        return errors

    @staticmethod
    def validate_against_provider_schema(
        json_spec: dict[str, Any], provider_schema: dict[str, Any]
    ) -> list[str]:
        """Validate JSON spec against a specific provider schema.

        Args:
            json_spec: The JSON specification to validate
            provider_schema: Provider schema from mcp_providers.yaml

        Returns:
            List of validation error messages (empty if valid)
        """
        errors: list[str] = []

        # Check if docker_image matches
        expected_image = provider_schema.get("docker_image")
        actual_image = json_spec.get("image")

        if expected_image and actual_image != expected_image:
            errors.append(f"Image '{actual_image}' does not match expected '{expected_image}'")

        # Validate environment variables against schema
        env_schema = provider_schema.get("env_vars", [])
        provided_env = json_spec.get("environment", {})

        # Check required environment variables
        for env_var in env_schema:
            var_name = env_var.get("name")
            is_required = env_var.get("required", False)

            if is_required and var_name not in provided_env:
                errors.append(f"Required environment variable '{var_name}' is missing")

        # Check for unknown environment variables
        schema_var_names = {var.get("name") for var in env_schema}
        for provided_var in provided_env:
            if provided_var not in schema_var_names:
                errors.append(
                    f"Unknown environment variable '{provided_var}' not defined in schema"
                )

        return errors

    @classmethod
    def validate_full_configuration(
        cls, json_spec: dict[str, Any], provider_schema: dict[str, Any] | None = None
    ) -> list[str]:
        """Perform complete validation of MCP configuration (sync wrapper).

        Args:
            json_spec: The JSON specification to validate
            provider_schema: Optional provider schema for additional validation

        Returns:
            List of validation error messages (empty if valid)
        """
        # Run async validation in sync context
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If we're in an async context, we need to create a task
                # For now, fall back to basic validation
                logger.warning("Running in async context, using basic validation only")
                errors = cls.validate_json_spec(json_spec)
                if provider_schema is not None:
                    errors.extend(cls.validate_against_provider_schema(json_spec, provider_schema))
                return errors
            else:
                return loop.run_until_complete(
                    cls.validate_full_configuration_async(json_spec, provider_schema)
                )
        except RuntimeError:
            # No event loop running, create a new one
            return asyncio.run(cls.validate_full_configuration_async(json_spec, provider_schema))

    @classmethod
    def is_valid_configuration(
        cls, json_spec: dict[str, Any], provider_schema: dict[str, Any] | None = None
    ) -> bool:
        """Check if configuration is valid.

        Args:
            json_spec: The JSON specification to validate
            provider_schema: Optional provider schema for additional validation

        Returns:
            True if valid, False otherwise
        """
        errors = cls.validate_full_configuration(json_spec, provider_schema)
        return len(errors) == 0
