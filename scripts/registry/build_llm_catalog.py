#!/usr/bin/env python3
"""Regenerate the published llm-models.json catalog from LiteLLM's price table.

The catalog on S3 was originally produced by a throwaway local script whose only
surviving trace is the ``metadata`` block it wrote. This rebuilds it from that
recorded spec so the catalog stops being reproducible on exactly one laptop:

  source          LiteLLM model_prices_and_context_window_backup.json
  allowed_modes   chat, completion, embedding, responses
  context_window  <- max_input_tokens
  model_name      the LiteLLM key with its leading "<provider>/" stripped, because
                  the SDK calls LiteLLM as provider_type/model_name
  plus the AgentArea bootstrap models, carried over from the current catalog

Models whose provider is absent from llm-providers.json are dropped: the sync
rejects them anyway ("Provider '<key>' not found"), and adding a provider needs
an icon asset published alongside it, which is not this script's job. Whatever is
dropped is reported rather than silently omitted.

Usage:
    python scripts/registry/build_llm_catalog.py -o registry/system/llm-models.json
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ALLOWED_MODES = ("chat", "completion", "embedding", "responses")

S3_BASE = "https://agentarea-mcp-registry.s3.amazonaws.com/registry/system"
DEFAULT_PROVIDERS = f"{S3_BASE}/llm-providers.json"
DEFAULT_CURRENT = f"{S3_BASE}/llm-models.json"

DEFAULT_LITELLM = (
    Path(__file__).resolve().parents[2]
    / "agentarea-platform/.venv/lib/python3.12/site-packages/litellm"
    / "model_prices_and_context_window_backup.json"
)

# Provider keys whose display name does not survive a naive title-case.
PROVIDER_DISPLAY = {
    "ai21": "AI21",
    "aleph_alpha": "Aleph Alpha",
    "amazon_nova": "Amazon Nova",
    "azure": "Azure OpenAI",
    "azure_ai": "Azure AI",
    "azure_text": "Azure Text",
    "bedrock": "Bedrock",
    "bedrock_converse": "Bedrock Converse",
    "openai": "OpenAI",
    "openrouter": "OpenRouter",
    "text-completion-openai": "OpenAI Text",
    "vertex_ai": "Vertex AI",
    "xai": "xAI",
}


def load_json(source: str | Path) -> Any:
    text = str(source)
    if text.startswith(("http://", "https://")):
        with urllib.request.urlopen(text) as response:
            return json.load(response)
    return json.loads(Path(source).read_text())


def provider_display(key: str) -> str:
    if key in PROVIDER_DISPLAY:
        return PROVIDER_DISPLAY[key]
    return key.replace("_", " ").replace("-", " ").title()


def format_context(tokens: int) -> str:
    if tokens >= 1_000_000:
        millions = tokens / 1_000_000
        return f"{millions:.0f}M" if millions == int(millions) else f"{millions:.1f}M"
    thousands = tokens / 1000
    return f"{thousands:.0f}K" if thousands == int(thousands) else f"{thousands:.1f}K"


def format_price(cost_per_token: float) -> str:
    per_million = cost_per_token * 1_000_000
    if abs(per_million - round(per_million)) < 1e-9:
        return str(round(per_million))
    digits = f"{per_million:.6f}".rstrip("0")
    whole, _, fraction = digits.partition(".")
    return f"{whole}.{fraction.ljust(2, '0')}"


def build_description(
    provider_key: str,
    model_name: str,
    mode: str,
    context_window: int,
    max_output_tokens: int | None,
    entry: dict[str, Any],
) -> str:
    parts = [f"{provider_display(provider_key)} {mode} model: {model_name}."]
    sentence = f"{format_context(context_window)}-token context"
    if mode != "embedding" and max_output_tokens and max_output_tokens != context_window:
        sentence += f", up to {max_output_tokens:,} output tokens"
    parts.append(sentence + ".")

    capabilities = []
    if entry.get("supports_vision"):
        capabilities.append("vision")
    if entry.get("supports_reasoning"):
        capabilities.append("reasoning")
    if entry.get("supports_function_calling"):
        capabilities.append("tool calling")
    if capabilities:
        parts.append(f"Supports {', '.join(capabilities)}.")

    parts.append(
        f"Pricing: ${format_price(entry['input_cost_per_token'])}/M input, "
        f"${format_price(entry['output_cost_per_token'])}/M output."
    )
    return " ".join(parts)


def strip_provider_prefix(key: str, provider_key: str) -> str:
    prefix = f"{provider_key}/"
    return key[len(prefix) :] if key.startswith(prefix) else key


def build_models(
    litellm: dict[str, Any], known_providers: set[str]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    models: list[dict[str, Any]] = []
    dropped = {"mode": 0, "unpriced": 0, "no_context": 0, "unknown_provider": 0}
    unknown: set[str] = set()

    for key, entry in litellm.items():
        if key == "sample_spec" or not isinstance(entry, dict):
            continue
        mode = entry.get("mode")
        if mode not in ALLOWED_MODES:
            dropped["mode"] += 1
            continue
        provider_key = entry.get("litellm_provider")
        if not provider_key:
            dropped["unknown_provider"] += 1
            continue
        if provider_key not in known_providers:
            dropped["unknown_provider"] += 1
            unknown.add(provider_key)
            continue
        if entry.get("input_cost_per_token") is None or entry.get("output_cost_per_token") is None:
            dropped["unpriced"] += 1
            continue
        context_window = entry.get("max_input_tokens") or entry.get("max_tokens")
        if not isinstance(context_window, int) or context_window <= 0:
            dropped["no_context"] += 1
            continue

        model_name = strip_provider_prefix(key, provider_key)
        max_output_tokens = entry.get("max_output_tokens")
        models.append(
            {
                "provider_key": provider_key,
                "model_name": model_name,
                "display_name": model_name,
                "description": build_description(
                    provider_key, model_name, mode, context_window, max_output_tokens, entry
                ),
                "context_window": context_window,
                "max_output_tokens": max_output_tokens,
                "input_cost_per_token": entry["input_cost_per_token"],
                "output_cost_per_token": entry["output_cost_per_token"],
                "supports_function_calling": bool(entry.get("supports_function_calling")),
                "is_active": True,
                "tags": [f"mode:{mode}", f"provider:{provider_key}", "source:litellm"],
            }
        )

    dropped["unknown_provider_keys"] = sorted(unknown)  # type: ignore[assignment]
    return models, dropped


def bootstrap_models(current: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        model
        for model in current.get("models", [])
        if "agentarea-bootstrap" in (model.get("tags") or [])
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--litellm-json", default=str(DEFAULT_LITELLM))
    parser.add_argument("--providers-json", default=DEFAULT_PROVIDERS)
    parser.add_argument("--current-json", default=DEFAULT_CURRENT)
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()

    litellm = load_json(args.litellm_json)
    providers = load_json(args.providers_json)
    current = load_json(args.current_json)

    known = {p["provider_key"] for p in providers.get("providers", []) if p.get("provider_key")}
    models, dropped = build_models(litellm, known)

    carried = bootstrap_models(current)
    models.extend(carried)

    previous = {(m.get("provider_key"), m.get("model_name")) for m in current.get("models", [])}
    added = [m for m in models if (m["provider_key"], m["model_name"]) not in previous]

    catalog = {
        "metadata": {
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "source": "LiteLLM model_prices_and_context_window_backup.json "
            "plus AgentArea bootstrap models",
            "litellm_source_file": str(args.litellm_json),
            "provider_count": len({m["provider_key"] for m in models}),
            "model_count": len(models),
            "allowed_modes": list(ALLOWED_MODES),
            "note": "Model names strip a leading provider prefix because AgentArea SDK "
            "calls LiteLLM as provider_type/model_name.",
            "description_format": "provider/mode/capabilities/pricing summary generated "
            "from registry fields",
        },
        "models": models,
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")

    print(f"wrote {output} — {len(models)} models ({len(carried)} bootstrap carried over)")
    print(f"  new since the current catalog: {len(added)}")
    print(f"  dropped — wrong mode: {dropped['mode']}")
    print(f"  dropped — no price:   {dropped['unpriced']}")
    print(f"  dropped — no context: {dropped['no_context']}")
    print(f"  dropped — provider not in llm-providers.json: {dropped['unknown_provider']}")
    unknown_keys = dropped["unknown_provider_keys"]
    if unknown_keys:
        print(f"    those providers ({len(unknown_keys)}): {', '.join(unknown_keys)}")
        print("    add them to llm-providers.json (with an icon asset) to pick their models up")
    return 0


if __name__ == "__main__":
    sys.exit(main())
