#!/usr/bin/env python3
"""Export OpenAPI schema from FastAPI app without running the server.

Usage:
    python scripts/export-openapi.py > openapi.json
    python scripts/export-openapi.py -o agentarea-webapp/src/api/openapi.json
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Provide dummy values for required env vars so the app can initialize
# without real services. Only the OpenAPI schema is extracted — no connections are made.
_DUMMY_ENV = {
    "WORKFLOW__TEMPORAL_SERVER_URL": "http://localhost:7233",
    "WORKFLOW__TEMPORAL_NAMESPACE": "default",
    "WORKFLOW__TEMPORAL_TASK_QUEUE": "agent-tasks",
    "KRATOS_JWKS_B64": "eyJrZXlzIjpbXX0=",  # {"keys":[]} - empty JWKS, enough for schema export
}
for key, value in _DUMMY_ENV.items():
    os.environ.setdefault(key, value)

# Add the platform root so uv workspace imports resolve
platform_root = Path(__file__).resolve().parent.parent / "agentarea-platform"
sys.path.insert(0, str(platform_root / "apps" / "api"))
sys.path.insert(0, str(platform_root / "libs" / "common"))
sys.path.insert(0, str(platform_root / "libs" / "execution"))
sys.path.insert(0, str(platform_root / "libs" / "llm"))
sys.path.insert(0, str(platform_root / "libs" / "mcp"))


def _sort_dict(obj):
    """Recursively sort dict keys for deterministic output."""
    if isinstance(obj, dict):
        return {k: _sort_dict(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return [_sort_dict(item) for item in obj]
    return obj


def export_schema() -> dict:
    from agentarea_api.main import create_app

    app = create_app()
    schema = app.openapi()
    # Sort keys for deterministic output across environments
    return _sort_dict(schema)


def main():
    parser = argparse.ArgumentParser(description="Export OpenAPI schema")
    parser.add_argument("-o", "--output", help="Output file path (default: stdout)")
    args = parser.parse_args()

    schema = export_schema()
    spec_json = json.dumps(schema, indent=2)

    if args.output:
        Path(args.output).write_text(spec_json + "\n")
        print(f"Wrote OpenAPI spec to {args.output}", file=sys.stderr)
    else:
        print(spec_json)


if __name__ == "__main__":
    main()
