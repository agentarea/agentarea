#!/usr/bin/env python3
"""Fetch all MCP servers from public registry and save in standard format.

The output preserves the official MCP registry schema so our RegistryService
can parse it natively via _parse_standard_mcp_registry().

Only latest versions are included. Deduplication by server name.
"""

import json
import sys
import time
import urllib.request
from datetime import datetime

REGISTRY_BASE_URL = "https://registry.modelcontextprotocol.io/v0.1/servers"


def fetch_page(limit: int = 100, cursor: str | None = None) -> dict:
    url = f"{REGISTRY_BASE_URL}?limit={limit}"
    if cursor:
        url += f"&cursor={cursor}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_all_servers(limit: int = 100) -> list:
    all_servers = []
    cursor = None
    page = 0
    while True:
        page += 1
        try:
            data = fetch_page(limit=limit, cursor=cursor)
        except Exception as e:
            print(f"  Error on page {page}: {e}", file=sys.stderr)
            break
        servers = data.get("servers", [])
        if not servers:
            break
        all_servers.extend(servers)
        next_cursor = data.get("metadata", {}).get("nextCursor")
        print(f"  Page {page}: +{len(servers)} (total: {len(all_servers)})", file=sys.stderr)
        if not next_cursor:
            break
        cursor = next_cursor
        time.sleep(0.1)
    return all_servers


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Fetch MCP public registry (standard format)")
    parser.add_argument("--output", "-o", default="mcp-servers-registry.json", help="Output file")
    parser.add_argument("--stats", "-s", action="store_true", help="Print stats")
    args = parser.parse_args()

    print("Fetching from MCP public registry...", file=sys.stderr)
    raw = fetch_all_servers()
    print(f"Fetched {len(raw)} raw entries", file=sys.stderr)

    # Deduplicate: keep only isLatest entries, one per server name
    seen = set()
    unique = []
    for entry in raw:
        server = entry.get("server", {})
        meta = entry.get("_meta", {}).get("io.modelcontextprotocol.registry/official", {})
        name = server.get("name", "")
        if not name or name in seen:
            continue
        if not meta.get("isLatest", False):
            continue
        seen.add(name)
        unique.append(entry)

    output = {
        "metadata": {
            "source": REGISTRY_BASE_URL,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "total_count": len(unique),
        },
        "servers": unique,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(unique)} unique latest servers to {args.output}", file=sys.stderr)

    if args.stats:
        has_remotes = sum(1 for e in unique if e.get("server", {}).get("remotes"))
        has_packages = sum(1 for e in unique if e.get("server", {}).get("packages"))
        has_both = sum(
            1 for e in unique
            if e.get("server", {}).get("remotes") and e.get("server", {}).get("packages")
        )

        # Count no-auth remotes
        no_auth = 0
        for e in unique:
            for r in e.get("server", {}).get("remotes", []):
                headers = r.get("headers", {})
                if isinstance(headers, list):
                    h = {}
                    for item in headers:
                        if isinstance(item, dict):
                            h.update(item)
                    headers = h
                if not headers.get("Authorization"):
                    no_auth += 1
                    break

        pkg_types = {}
        for e in unique:
            for p in e.get("server", {}).get("packages", []):
                rt = p.get("registryType", "unknown")
                pkg_types[rt] = pkg_types.get(rt, 0) + 1

        print(f"\nStats:", file=sys.stderr)
        print(f"  With remotes: {has_remotes}", file=sys.stderr)
        print(f"  With packages: {has_packages}", file=sys.stderr)
        print(f"  With both: {has_both}", file=sys.stderr)
        print(f"  No-auth remote: {no_auth}", file=sys.stderr)
        print(f"  Package types: {pkg_types}", file=sys.stderr)


if __name__ == "__main__":
    main()
