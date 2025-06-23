#!/usr/bin/env python3
"""
Validate that all provider icons exist and are accessible.
"""

import yaml
import os
from pathlib import Path


def validate_provider_icons():
    """Validate all provider icons exist."""

    # Load providers.yaml
    with open("data/providers.yaml", "r") as f:
        providers_data = yaml.safe_load(f)

    missing_icons = []
    invalid_icons = []

    for provider_key, provider_data in providers_data["providers"].items():
        icon_path = provider_data.get("icon")

        if not icon_path:
            missing_icons.append(f"{provider_key}: No icon specified")
            continue

        # Check if file exists
        if not os.path.exists(icon_path):
            missing_icons.append(f"{provider_key}: {icon_path} does not exist")
            continue

        # Check if it's a valid image file
        icon_ext = Path(icon_path).suffix.lower()
        if icon_ext not in [".svg", ".png", ".jpg", ".jpeg"]:
            invalid_icons.append(f"{provider_key}: {icon_path} - unsupported format")

    # Report results
    if missing_icons:
        print("❌ Missing Icons:")
        for icon in missing_icons:
            print(f"  - {icon}")

    if invalid_icons:
        print("❌ Invalid Icons:")
        for icon in invalid_icons:
            print(f"  - {icon}")

    if not missing_icons and not invalid_icons:
        print("✅ All provider icons are valid!")
        return True

    return False


if __name__ == "__main__":
    validate_provider_icons()
