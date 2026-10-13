"""Every LLM call to a provider config's endpoint states who set the address.

GHSA-pprc-x767-m6jg came from one call path that skipped the outbound guard
while its neighbour applied it. These checks fail when a new path does the same:

- every ``LLMModel(...)`` in platform code passes ``endpoint_policy=``, so the
  choice between "operator's address, call as given" and "member's address,
  hold to the policy" is made at the call site, never by default;
- every module that hands an ``endpoint_url`` to LiteLLM itself resolves the
  policy through ``endpoint_policy_for``.
"""

from __future__ import annotations

import ast
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
SDK = PLATFORM_ROOT / "libs" / "agentarea-agents-sdk" / "agentarea_agents_sdk"
LITELLM_CALLS = {"acompletion", "aimage_generation", "aembedding", "aspeech", "atranscription"}


def _production_modules() -> list[Path]:
    modules = []
    for top in ("apps", "libs"):
        for path in (PLATFORM_ROOT / top).rglob("*.py"):
            parts = set(path.relative_to(PLATFORM_ROOT).parts)
            if parts & {"tests", "test", ".venv", "migrations", "alembic"}:
                continue
            if path.is_relative_to(SDK):
                continue
            modules.append(path)
    return modules


def _called_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def test_every_llm_model_states_its_endpoint_policy():
    missing = []
    for path in _production_modules():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _called_name(node) != "LLMModel":
                continue
            if not any(keyword.arg == "endpoint_policy" for keyword in node.keywords):
                missing.append(f"{path.relative_to(PLATFORM_ROOT)}:{node.lineno}")
    assert not missing, f"LLMModel(...) without endpoint_policy=: {missing}"


def test_every_direct_litellm_call_with_an_endpoint_resolves_the_policy():
    missing = []
    for path in _production_modules():
        source = path.read_text()
        if "endpoint_url" not in source:
            continue
        tree = ast.parse(source, filename=str(path))
        calls_litellm = any(
            isinstance(node, ast.Call) and _called_name(node) in LITELLM_CALLS
            for node in ast.walk(tree)
        )
        if calls_litellm and "endpoint_policy_for" not in source:
            missing.append(str(path.relative_to(PLATFORM_ROOT)))
    assert not missing, f"LiteLLM called with an endpoint_url but no policy: {missing}"
