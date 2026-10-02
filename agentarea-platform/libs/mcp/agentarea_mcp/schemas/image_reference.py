"""Container image reference validation.

The image of a docker MCP server ends up in ``docker run`` argv, in the
position the runtime reads flags from. A value that is not a plain OCI
reference (``--volume=/var/run/docker.sock:...``, ``--privileged``) would be
parsed as a flag and hand the container the host. The MCP manager refuses
such values too; refusing them here turns a late start failure into a 422.
"""

from __future__ import annotations

import re
from typing import Any

_COMPONENT = r"[a-z0-9]+(?:(?:[._]|__|[-]+)[a-z0-9]+)*"
_DOMAIN_LABEL = r"(?:[a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9])"
IMAGE_REFERENCE = re.compile(
    rf"^(?:{_DOMAIN_LABEL}(?:\.{_DOMAIN_LABEL})*(?::[0-9]+)?/)?"
    rf"{_COMPONENT}(?:/{_COMPONENT})*"
    r"(?::[\w][\w.-]{0,127})?"
    r"(?:@[A-Za-z][A-Za-z0-9]*(?:[-_+.][A-Za-z][A-Za-z0-9]*)*:[0-9a-fA-F]{32,})?$"
)
MAX_IMAGE_REFERENCE_LENGTH = 255


def validate_image_reference(image: str) -> str:
    if len(image) > MAX_IMAGE_REFERENCE_LENGTH or not IMAGE_REFERENCE.fullmatch(image):
        raise ValueError(f"{image!r} is not a valid container image reference")
    return image


def validate_optional_image_reference(image: str | None) -> str | None:
    return None if image is None else validate_image_reference(image)


def validate_spec_image(json_spec: dict[str, Any] | None) -> dict[str, Any] | None:
    """Refuse a ``json_spec`` whose ``image`` is not a plain reference."""
    if json_spec is None:
        return None
    image = json_spec.get("image")
    if image is None:
        return json_spec
    if not isinstance(image, str):
        raise ValueError("json_spec.image must be a string")
    validate_image_reference(image)
    return json_spec
