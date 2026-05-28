#!/usr/bin/env python3
"""Fetch local logo assets for the remote MCP OAuth catalog.

The script uses official/remote endpoint domains to discover favicon/logo
assets, stores them under the API static tree, and enriches both the CSV and
standard MCP registry JSON with `icons`.
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

CSV_PATH = Path("research/mcp-remote-oauth-catalog.csv")
REGISTRY_PATHS = [
    Path("research/mcp-remote-oauth-registry.json"),
    Path("agentarea-platform/apps/api/agentarea_api/data/mcp-remote-oauth-registry.json"),
]
STATIC_DIR = Path("agentarea-platform/apps/api/agentarea_api/static/icons/mcp")
PUBLIC_PREFIX = "/api/static/icons/mcp"

USER_AGENT = "Mozilla/5.0 (compatible; AgentAreaLogoFetcher/1.0)"
TIMEOUT = 4
MAX_BYTES = 1_500_000

DOMAIN_OVERRIDES = {
    "GitHub": "github.com",
    "Google Kubernetes Engine": "cloud.google.com",
    "Shopify Storefront": "shopify.com",
    "PlanetScale": "planetscale.com",
    "TigerData Timescale": "tigerdata.com",
    "v0.dev": "v0.dev",
    "Weights & Biases": "wandb.ai",
    "ThoughtSpot": "thoughtspot.com",
    "JFrog": "jfrog.com",
    "Dremio Cloud": "dremio.com",
    "Databricks": "databricks.com",
    "Elastic": "elastic.co",
    "Snowflake": "snowflake.com",
    "Visier": "visier.com",
    "You.com": "you.com",
    "WordPress.com": "wordpress.com",
    "monday.com": "monday.com",
    "CustomGPT.ai": "customgpt.ai",
}

HOST_OVERRIDES = {
    "api.githubcopilot.com": "github.com",
    "container.googleapis.com": "cloud.google.com",
    "api.dashboard.plaid.com": "plaid.com",
    "mcp.pscale.dev": "planetscale.com",
    "agent.thoughtspot.app": "thoughtspot.com",
    "mcp.withwandb.com": "wandb.ai",
    "public-api.wordpress.com": "wordpress.com",
    "asset-management.mcp.cloudinary.com": "cloudinary.com",
    "mcp.tigerdata.com": "tigerdata.com",
}


class IconParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.icons: list[dict[str, str]] = []
        self.og_images: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k.lower(): v or "" for k, v in attrs}
        if tag.lower() == "link":
            rel = attr.get("rel", "").lower()
            href = attr.get("href", "")
            if href and ("icon" in rel or "mask-icon" in rel):
                self.icons.append(
                    {
                        "href": href,
                        "rel": rel,
                        "sizes": attr.get("sizes", ""),
                        "type": attr.get("type", ""),
                    }
                )
        elif tag.lower() == "meta":
            prop = attr.get("property", "").lower() or attr.get("name", "").lower()
            content = attr.get("content", "")
            if content and prop in {"og:image", "twitter:image"}:
                self.og_images.append(content)


def slugify(value: str) -> str:
    value = value.lower().replace("&", "and")
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "unknown"


def host_from_url(url: str) -> str:
    if not url or "<" in url or "{" in url:
        return ""
    parsed = urllib.parse.urlparse(url if "://" in url else f"https://{url}")
    return parsed.netloc.lower()


def registrable_domain(host: str) -> str:
    if not host:
        return ""
    if host in HOST_OVERRIDES:
        return HOST_OVERRIDES[host]
    parts = [p for p in host.split(".") if p and p not in {"www"}]
    if len(parts) <= 2:
        return ".".join(parts)
    return ".".join(parts[-2:])


def company_domain(row: dict[str, str]) -> str:
    company = row["company"]
    if company in DOMAIN_OVERRIDES:
        return DOMAIN_OVERRIDES[company]
    host = host_from_url(row.get("remote_url", ""))
    domain = registrable_domain(host)
    if domain and domain not in {"apigene.ai", "github.com"}:
        return domain
    source_host = host_from_url(row.get("source_url", ""))
    source_domain = registrable_domain(source_host)
    if source_domain and source_domain != "apigene.ai":
        return source_domain
    return f"{slugify(company).replace('-', '')}.com"


def request_bytes(url: str, max_bytes: int = MAX_BYTES) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:  # noqa: S310
        content_type = response.headers.get("Content-Type", "")
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"asset too large: {url}")
    return data, content_type


def discover_icons(domain: str) -> list[str]:
    candidates: list[str] = [
        f"https://www.google.com/s2/favicons?domain={urllib.parse.quote(domain)}&sz=128"
    ]
    for scheme in ("https", "http"):
        root = f"{scheme}://{domain}"
        try:
            html, content_type = request_bytes(root, max_bytes=500_000)
        except Exception:
            continue
        if "html" not in content_type.lower() and b"<html" not in html[:1000].lower():
            continue
        parser = IconParser()
        try:
            parser.feed(html.decode("utf-8", "ignore"))
        except Exception:
            continue
        scored = sorted(parser.icons, key=icon_score, reverse=True)
        for icon in scored:
            candidates.append(urllib.parse.urljoin(root, icon["href"]))
        for image in parser.og_images[:2]:
            candidates.append(urllib.parse.urljoin(root, image))
        break
    candidates.extend([f"https://{domain}/favicon.svg", f"https://{domain}/favicon.ico"])
    seen: set[str] = set()
    unique: list[str] = []
    for url in candidates:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def icon_score(icon: dict[str, str]) -> tuple[int, int]:
    href = icon.get("href", "").lower()
    rel = icon.get("rel", "")
    sizes = icon.get("sizes", "")
    score = 0
    if href.endswith(".svg"):
        score += 30
    if "apple" in rel:
        score += 20
    if "shortcut" not in rel and "icon" in rel:
        score += 10
    numbers = [int(x) for x in re.findall(r"\d+", sizes)]
    size = max(numbers) if numbers else 0
    return score, size


def extension_for(url: str, content_type: str, data: bytes) -> str:
    path = urllib.parse.urlparse(url).path.lower()
    for ext in (".svg", ".png", ".jpg", ".jpeg", ".webp", ".ico"):
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    content_type = content_type.lower()
    if "svg" in content_type or data.lstrip().startswith(b"<svg"):
        return ".svg"
    if "png" in content_type or data.startswith(b"\x89PNG"):
        return ".png"
    if "jpeg" in content_type or data.startswith(b"\xff\xd8"):
        return ".jpg"
    if "webp" in content_type or data.startswith(b"RIFF"):
        return ".webp"
    if "icon" in content_type or data.startswith(b"\x00\x00\x01\x00"):
        return ".ico"
    return ".png"


def download_icon(company: str, domain: str) -> dict[str, str]:
    slug = slugify(company)
    existing = sorted(STATIC_DIR.glob(f"{slug}.*"))
    if existing:
        path = existing[0]
        return {
            "slug": slug,
            "domain": domain,
            "source_logo_url": f"https://www.google.com/s2/favicons?domain={urllib.parse.quote(domain)}&sz=128",
            "logo_path": f"{PUBLIC_PREFIX}/{path.name}",
            "local_path": str(path),
        }
    for url in discover_icons(domain):
        try:
            data, content_type = request_bytes(url)
        except Exception:
            continue
        ext = extension_for(url, content_type, data)
        if len(data) < 100:
            continue
        path = STATIC_DIR / f"{slug}{ext}"
        path.write_bytes(data)
        return {
            "slug": slug,
            "domain": domain,
            "source_logo_url": url,
            "logo_path": f"{PUBLIC_PREFIX}/{path.name}",
            "local_path": str(path),
        }
    raise RuntimeError(f"no logo found for {company} ({domain})")


def enrich_csv(results: dict[str, dict[str, str]]) -> None:
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        original_fields = list(reader.fieldnames or [])
    extra = ["logo_path", "logo_source_url", "logo_domain"]
    fieldnames = original_fields + [f for f in extra if f not in original_fields]
    for row in rows:
        result = results.get(row["company"], {})
        row["logo_path"] = result.get("logo_path", row.get("logo_path", ""))
        row["logo_source_url"] = result.get("source_logo_url", row.get("logo_source_url", ""))
        row["logo_domain"] = result.get("domain", row.get("logo_domain", ""))
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def enrich_registry(results: dict[str, dict[str, str]]) -> None:
    for path in REGISTRY_PATHS:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for entry in payload.get("servers", []):
            server = entry.get("server", {})
            title = server.get("title")
            result = results.get(title)
            if not result:
                continue
            server["icons"] = [
                {
                    "src": result["logo_path"],
                    "mimeType": mime_type_for(result["logo_path"]),
                    "sizes": ["128x128"],
                }
            ]
            server.setdefault("metadata", {})
            server["metadata"]["agentarea:logo_domain"] = result["domain"]
            server["metadata"]["agentarea:logo_source_url"] = result["source_logo_url"]
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def mime_type_for(path: str) -> str:
    if path.endswith(".svg"):
        return "image/svg+xml"
    if path.endswith(".jpg"):
        return "image/jpeg"
    if path.endswith(".webp"):
        return "image/webp"
    if path.endswith(".ico"):
        return "image/x-icon"
    return "image/png"


def main() -> int:
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    results: dict[str, dict[str, str]] = {}
    failures: list[str] = []
    for row in rows:
        company = row["company"]
        domain = company_domain(row)
        try:
            result = download_icon(company, domain)
            results[company] = result
            print(f"ok {company}: {result['logo_path']} <- {result['source_logo_url']}", flush=True)
        except Exception as exc:
            failures.append(f"{company} ({domain}): {exc}")
            print(f"fail {company} ({domain}): {exc}", file=sys.stderr, flush=True)
        time.sleep(0.05)

    enrich_csv(results)
    enrich_registry(results)

    print(f"\nlogos: {len(results)} ok, {len(failures)} failed")
    if failures:
        print("failures:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
    return 0 if len(results) == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
