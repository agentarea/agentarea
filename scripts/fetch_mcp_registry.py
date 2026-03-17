#!/usr/bin/env python3
"""Fetch all MCP servers from https://registry.modelcontextprotocol.io"""
import argparse
import json
import time
import urllib.request
import urllib.error
from datetime import datetime


REGISTRY_BASE_URL = "https://registry.modelcontextprotocol.io/v0.1/servers"


def fetch_page(limit: int = 100, cursor: str = None) -> dict:
    url = f"{REGISTRY_BASE_URL}?limit={limit}"
    if cursor:
        url += f"&cursor={cursor}"
    
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_all_servers(limit: int = 100, max_servers: int = None, delay: float = 0.1) -> list:
    all_servers = []
    cursor = None
    page = 0
    
    print(f"Fetching from {REGISTRY_BASE_URL}")
    print(f"Page size: {limit}, Max: {max_servers or 'unlimited'}")
    print("-" * 60)
    
    while True:
        page += 1
        data = fetch_page(limit=limit, cursor=cursor)
        servers = data.get("servers", [])
        
        if not servers:
            break
        
        all_servers.extend(servers)
        next_cursor = data.get("metadata", {}).get("nextCursor")
        
        print(f"Page {page}: +{len(servers)} | Total: {len(all_servers)}")
        
        if max_servers and len(all_servers) >= max_servers:
            all_servers = all_servers[:max_servers]
            break
        
        if not next_cursor:
            break
        
        cursor = next_cursor
        time.sleep(delay)
    
    return all_servers


def extract_server_info(server_entry: dict) -> dict:
    server = server_entry.get("server", {})
    meta = server_entry.get("_meta", {}).get("io.modelcontextprotocol.registry/official", {})
    
    return {
        "identifier": server.get("name"),
        "title": server.get("title"),
        "description": server.get("description"),
        "version": server.get("version"),
        "website_url": server.get("websiteUrl"),
        "repository": server.get("repository"),
        "remotes": server.get("remotes", []),
        "packages": server.get("packages", []),
        "icons": server.get("icons", []),
        "meta": {
            "status": meta.get("status"),
            "published_at": meta.get("publishedAt"),
            "updated_at": meta.get("updatedAt"),
            "is_latest": meta.get("isLatest"),
        }
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch all MCP servers from official registry")
    parser.add_argument("--output", "-o", default="mcps.json", help="Output JSON file")
    parser.add_argument("--limit", "-l", type=int, default=100, help="Page size")
    parser.add_argument("--max", "-m", type=int, default=None, help="Max servers to fetch")
    parser.add_argument("--raw", "-r", action="store_true", help="Save raw API response")
    args = parser.parse_args()
    
    start_time = time.time()
    
    raw_servers = fetch_all_servers(limit=args.limit, max_servers=args.max)
    
    if args.raw:
        servers = raw_servers
    else:
        servers = [extract_server_info(s) for s in raw_servers]
    
    output = {
        "metadata": {
            "source": REGISTRY_BASE_URL,
            "fetched_at": datetime.utcnow().isoformat() + "Z",
            "total_count": len(servers),
            "fetch_duration_seconds": round(time.time() - start_time, 2),
        },
        "servers": servers,
    }
    
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print("-" * 60)
    print(f"Fetched {len(servers)} servers in {output['metadata']['fetch_duration_seconds']}s")
    print(f"Saved to: {args.output}")
    
    if not args.raw:
        remote_types = {}
        for s in servers:
            for r in s.get("remotes", []):
                rt = r.get("type", "unknown")
                remote_types[rt] = remote_types.get(rt, 0) + 1
        
        print("\nRemote types:")
        for rt, count in sorted(remote_types.items(), key=lambda x: -x[1]):
            print(f"  {rt}: {count}")


if __name__ == "__main__":
    main()
