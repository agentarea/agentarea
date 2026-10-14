"""Outbound clients built outside ``agentarea_common.outbound`` only ever go down.

A request the platform sends outside its process should leave through
``outbound_client(destination)``, which decides the trust for it: a member's
address vetted and pinned on every hop, a vendor through the egress proxy, an
internal service directly. A client built anywhere else decides that on its own,
and GHSA-pprc-x767-m6jg came from one such path.

Three things are counted per production module and held to the checked-in
baseline (``outbound_ratchet_baseline.json``):

- ``http``: an ``httpx``/``httpx2``/``aiohttp``/``requests`` client or one-shot
  request, or ``urlopen``,
- ``mail``: an SMTP or IMAP connection,
- ``litellm``: a LiteLLM call, which connects with LiteLLM's own client.

A count above the baseline fails: send the request through ``outbound_client``.
A count below the baseline also fails, so the lower number is written down and
cannot creep back: regenerate with

    uv run python tests/unit/test_outbound_ratchet.py
"""

from __future__ import annotations

import ast
import json
from collections import Counter
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
BASELINE = Path(__file__).with_name("outbound_ratchet_baseline.json")
KINDS = ("http", "mail", "litellm")
# The outbound layer itself.
LAYER = {
    "libs/common/agentarea_common/outbound.py",
    "libs/common/agentarea_common/utils/url_safety.py",
}

HTTP_MODULES = {"httpx", "httpx2", "aiohttp", "requests"}
HTTP_NAMES = {
    "AsyncClient",
    "Client",
    "ClientSession",
    "Session",
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "head",
    "options",
    "request",
    "stream",
}
MAIL_NAMES = {
    ("smtplib", "SMTP"),
    ("smtplib", "SMTP_SSL"),
    ("aiosmtplib", "SMTP"),
    ("aiosmtplib", "send"),
    ("imaplib", "IMAP4"),
    ("imaplib", "IMAP4_SSL"),
    ("aioimaplib", "IMAP4"),
    ("aioimaplib", "IMAP4_SSL"),
}
LITELLM_NAMES = {
    "acompletion",
    "completion",
    "aimage_generation",
    "image_generation",
    "aembedding",
    "embedding",
    "aspeech",
    "atranscription",
    "asystemone",
    "systemone",
    "adecisions",
    "decisions",
}


def _production_modules() -> list[Path]:
    modules = []
    for root in ("libs", "apps"):
        for path in (PLATFORM_ROOT / root).glob("*/agentarea_*/**/*.py"):
            if "tests" not in path.relative_to(PLATFORM_ROOT).parts:
                modules.append(path)
    return sorted(modules)


def _imported(tree: ast.AST) -> dict[str, tuple[str, str]]:
    """Local name -> (module, name) for ``from <module> import <name> [as alias]``."""
    names = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                names[alias.asname or alias.name] = (node.module, alias.name)
    return names


def _module_aliases(tree: ast.AST) -> dict[str, str]:
    """Local name -> module for ``import <module> [as alias]``."""
    return {
        alias.asname or alias.name: alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }


def _kind(call: ast.Call, imported: dict[str, tuple[str, str]], modules: dict[str, str]) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        # Only an imported module: a local named ``requests`` is not the library.
        if func.value.id not in modules:
            return None
        target = (modules[func.value.id], func.attr)
    elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Attribute):
        # urllib.request.urlopen(...)
        target = ("", func.attr)
    elif isinstance(func, ast.Name) and func.id in imported:
        target = imported[func.id]
    else:
        return None
    module, name = target
    root = module.split(".")[0]
    if root in HTTP_MODULES and name in HTTP_NAMES:
        return "http"
    if name == "urlopen" and (module in {"", "urllib.request"} or root == "urllib"):
        return "http"
    if (root, name) in MAIL_NAMES:
        return "mail"
    if root == "litellm" and name in LITELLM_NAMES:
        return "litellm"
    return None


def _scan_source(source: str) -> Counter[str]:
    tree = ast.parse(source)
    imported, modules = _imported(tree), _module_aliases(tree)
    counts: Counter[str] = Counter()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            kind = _kind(node, imported, modules)
            if kind is not None:
                counts[kind] += 1
    return counts


def _current() -> dict[str, dict[str, int]]:
    current: dict[str, dict[str, int]] = {kind: {} for kind in KINDS}
    for path in _production_modules():
        module = str(path.relative_to(PLATFORM_ROOT))
        if module in LAYER:
            continue
        for kind, count in _scan_source(path.read_text(encoding="utf-8")).items():
            current[kind][module] = count
    return current


def _baseline() -> dict[str, dict[str, int]]:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def test_the_scan_sees_the_code_it_guards() -> None:
    """Guard against a scan that silently finds nothing."""
    current = _current()
    assert sum(current["http"].values()) > 30
    assert sum(current["mail"].values()) > 1
    assert sum(current["litellm"].values()) > 2


def test_every_way_of_naming_a_client_is_counted() -> None:
    source = (
        "import httpx\n"
        "import httpx2 as h2\n"
        "import aiosmtplib\n"
        "import litellm\n"
        "import urllib.request\n"
        "from aiohttp import ClientSession\n"
        "from urllib.request import urlopen as fetch\n"
        "from imaplib import IMAP4_SSL\n"
        "from agentarea_common.outbound import outbound_client\n"
        "httpx.AsyncClient()\n"
        "httpx.get('https://example.test')\n"
        "h2.AsyncClient()\n"
        "ClientSession()\n"
        "fetch('https://example.test')\n"
        "urllib.request.urlopen('https://example.test')\n"
        "aiosmtplib.SMTP(hostname='mail')\n"
        "IMAP4_SSL('mail')\n"
        "litellm.acompletion(model='m')\n"
        "outbound_client('vendor')\n"
        "httpx.Timeout(5)\n"
        "requests = {}\n"
        "requests.get('id')\n"
    )
    assert _scan_source(source) == {"http": 6, "mail": 2, "litellm": 1}


def test_outbound_clients_outside_the_layer_do_not_grow() -> None:
    current = _current()
    baseline = _baseline()
    grown = []
    shrunk = []
    for kind in KINDS:
        for module in sorted(set(current[kind]) | set(baseline.get(kind, {}))):
            now = current[kind].get(module, 0)
            then = baseline.get(kind, {}).get(module, 0)
            if now > then:
                grown.append(f"{kind}: {module} {then} -> {now}")
            elif now < then:
                shrunk.append(f"{kind}: {module} {then} -> {now}")
    assert not grown, (
        "outbound clients built outside agentarea_common.outbound grew:\n  "
        + "\n  ".join(grown)
        + "\n\nSend the request through outbound_client(Destination.MEMBER | VENDOR | "
        "INTERNAL), which decides the trust for where it goes."
    )
    assert not shrunk, (
        "fewer than the baseline -- lower it so the gain is kept:\n  "
        + "\n  ".join(shrunk)
        + "\n\n  uv run python tests/unit/test_outbound_ratchet.py"
    )


if __name__ == "__main__":
    BASELINE.write_text(json.dumps(_current(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {BASELINE.relative_to(PLATFORM_ROOT)}")
