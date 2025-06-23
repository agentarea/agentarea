#!/usr/bin/env python3
"""
Utility script to generate UUIDs for new LLM providers.

Usage:
    python generate_provider_uuid.py [provider_name]

If no provider name is provided, it will generate a random UUID.
If a provider name is provided, it will generate a deterministic UUID based on the name.
"""

import sys
import uuid
from typing import Optional


def generate_uuid(provider_name: Optional[str] = None) -> str:
    """Generate a UUID for a provider.

    Args:
        provider_name: Optional provider name for deterministic UUID generation

    Returns:
        UUID string
    """
    if provider_name:
        # Generate a deterministic UUID based on the provider name
        # This ensures the same provider name always gets the same UUID
        namespace = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
        provider_uuid = uuid.uuid5(namespace, provider_name)
        return str(provider_uuid)
    else:
        # Generate a random UUID
        return str(uuid.uuid4())


def main() -> None:
    """Main function to handle command line arguments and generate UUID."""
    if len(sys.argv) > 1:
        provider_name = sys.argv[1]
        generated_uuid = generate_uuid(provider_name)
        print(f"UUID for provider '{provider_name}': {generated_uuid}")
    else:
        generated_uuid = generate_uuid()
        print(f"Random UUID: {generated_uuid}")
        print("\nTo generate a deterministic UUID for a specific provider:")
        print("python generate_provider_uuid.py <provider_name>")


if __name__ == "__main__":
    main()
