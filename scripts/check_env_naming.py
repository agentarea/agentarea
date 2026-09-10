#!/usr/bin/env python3
"""Enforce the environment-variable naming scheme.

Every variable AgentArea reads is ``AGENTAREA_<DOMAIN>_<KEY>``. Names that
belong to somebody else — a third-party image, an SDK that reads the
environment itself, or the platform that starts our process — are listed in
WHITELIST and left alone.

Run from anywhere:  python scripts/check_env_naming.py
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MAX_LEN = 34
MAX_SEGMENTS_AFTER_DOMAIN = 3

DOMAINS = {
    "DB", "S3", "AUTH", "AUTHZ", "SECRET", "MCP", "SBX", "WF", "TASK", "TRIG",
    "CHAN", "EVT", "CORS", "LOG", "REDIS", "KAFKA", "TOOL", "K8S", "API",
    "HTTP", "OTEL", "EVENT",
}

# App-level names that carry no domain segment.
NO_DOMAIN = {
    "AGENTAREA_ENV", "AGENTAREA_DEBUG", "AGENTAREA_EDITION", "AGENTAREA_APP_NAME",
    "AGENTAREA_APP_URL", "AGENTAREA_LOCAL_HOST", "AGENTAREA_TOKEN",
    "AGENTAREA_BROKER", "AGENTAREA_THEME", "AGENTAREA_MAX_RETRIES",
    "AGENTAREA_RETRY_DELAY", "AGENTAREA_STREAM_TIMEOUT",
    "AGENTAREA_STARTUP_TIMEOUT", "AGENTAREA_SHUTDOWN_TIMEOUT",
    "AGENTAREA_TELEGRAM_WEBHOOK_URL",
    # Runtime identity handed to agent processes inside a sandbox.
    "AGENTAREA_WORKSPACE_ID", "AGENTAREA_TASK_ID", "AGENTAREA_WORKSPACE_ROOT",
    "AGENTAREA_INPUT_DIR", "AGENTAREA_API_KEY", "AGENTAREA_API_TOKEN",
    "AGENTAREA_MODEL_INSTANCE_ID",
}

# Not ours: third-party images, SDKs that read the environment directly, and
# the platform contract for a process's listen address.
WHITELIST = {
    # postgres image + libpq
    "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "POSTGRES_HOST",
    "POSTGRES_PORT", "POSTGRES_SSLMODE", "PGDATA", "PGHOST", "PGPORT",
    "PGUSER", "PGPASSWORD", "PGDATABASE",
    # temporal image
    "DB", "DB_PORT", "DBNAME", "POSTGRES_PWD", "POSTGRES_SEEDS",
    "DYNAMIC_CONFIG_FILE_PATH", "TEMPORAL_ADDRESS", "TEMPORAL_CLI_ADDRESS",
    "TEMPORAL_CORS_ORIGINS", "BIND_ON_IP", "TEMPORAL_DB", "KRATOS_DB",
    "HYDRA_DB", "KETO_DB", "OPENFGA_DB", "INFISICAL_DB",
    # ory images
    "DSN", "SECRETS_SYSTEM", "LOG_LEAK_SENSITIVE_VALUES",
    "KRATOS_SECRETS_COOKIE", "KRATOS_SECRETS_CIPHER",
    "HYDRA_SECRETS_SYSTEM", "HYDRA_SECRETS_COOKIE", "HYDRA_PAIRWISE_SALT",
    "AUTH_PROVIDER",
    "OIDC_GOOGLE_CLIENT_ID", "OIDC_GOOGLE_CLIENT_SECRET",
    "OIDC_GITHUB_CLIENT_ID", "OIDC_GITHUB_CLIENT_SECRET",
    # openfga image
    "OPENFGA_DATASTORE_ENGINE", "OPENFGA_DATASTORE_URI", "OPENFGA_LOG_FORMAT",
    "OPENFGA_IMAGE",
    # object storage images
    "RUSTFS_ACCESS_KEY", "RUSTFS_SECRET_KEY", "RUSTFS_REGION",
    "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD", "DOCUMENTS_BUCKET",
    "ARTIFACTS_BUCKET",
    # mailpit / smtp
    "MP_DATABASE", "MP_SMTP_AUTH_ACCEPT_ANY", "MP_SMTP_AUTH_ALLOW_INSECURE",
    "SMTP_PROTOCOL", "SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD",
    "SMTP_FROM_EMAIL", "SMTP_FROM_NAME", "SMTP_SKIP_SSL_VERIFY",
    "SMTP_DISABLE_STARTTLS",
    # aws sdk credential chain — also the sandbox credential-scrub denylist
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    "AWS_SECURITY_TOKEN", "AWS_WEB_IDENTITY_TOKEN_FILE",
    "AWS_SHARED_CREDENTIALS_FILE", "AWS_CONTAINER_AUTHORIZATION_TOKEN",
    "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "S3_ACCESS_KEY", "S3_SECRET_KEY",
    # otel sdk reads these itself
    "OTEL_SERVICE_NAME", "OTEL_EXPORTER_OTLP_PROTOCOL",
    "OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_HEADERS",
    "OTEL_RESOURCE_ATTRIBUTES", "OTEL_TRACES_EXPORTER",
    # llm vendor sdks
    "OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY",
    "OLLAMA_API_BASE", "LITELLM_CALLBACKS",
    # vendored @ory SDK reads these from the environment itself
    "ORY_SDK_URL", "NEXT_PUBLIC_ORY_SDK_URL", "ORY_PROJECT_API_TOKEN",
    "VERCEL_ENV", "VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL",
    "NEXT_PUBLIC_VERCEL_ENV", "NEXT_PUBLIC_VERCEL_URL",
    "NEXT_PUBLIC_VERCEL_PROJECT_PRODUCTION_URL", "CLIENT_ORY_SDK_URL",
    # next.js build contract
    "NODE_ENV", "NEXT_TELEMETRY_DISABLED", "NEXT_PUBLIC_APP_URL",
    "NEXT_PUBLIC_APP_VERSION", "NEXT_PUBLIC_API_URL", "NEXT_PUBLIC_KRATOS_URL",
    "NEXT_PUBLIC_NODE_ENV", "__NEXT_PRIVATE_ORIGIN",
    # proxy configuration, read by http clients themselves
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
    # platform / shell
    "PORT", "HOST", "PATH", "HOME", "USER", "CI", "VERSION", "TZ",
    "KUBERNETES_SERVICE_HOST", "KUBERNETES_SERVICE_PORT", "KUBECONFIG",
    "REGISTRIES_CONFIG",
}

# Fixture and tooling paths hold throwaway names, not deployed configuration.
NON_CONFIG = (
    "/tests/", "/test/", "/dev/", "/scripts/", "/e2e/", "/testdata/", "/testing/",
    "conftest.py", "_test.go", "_test.py", "test_utils.py", ".spec.ts", ".test.ts",
    "playwright.config",
    # Vendored @ory/elements-react and @ory/nextjs: upstream Apache-2.0 code.
    "agentarea-webapp/packages/",
)

UNIT_SUFFIX = re.compile(r"_(SECONDS|MS|MINUTES|HOURS|DAYS|BYTES)$")

# Durations belong in the value ("30s"), not the name. These two are still
# parsed as integer seconds by the Go activation path, so their names keep
# saying so rather than becoming ambiguous. Converting them to duration
# strings means touching per-request timeout validation — a separate change.
UNIT_SUFFIX_ALLOWED = {
    "AGENTAREA_SBX_MAX_EXEC_SECONDS",
    "AGENTAREA_SBX_EXEC_SECONDS",
}

SKIP_DIRS = re.compile(r"(\.venv|node_modules|/dist/|\.next|/vendor/|\.git/|/build/)")

GO_READ = re.compile(
    r"(?:os\.Getenv|os\.LookupEnv|\b\w*[eE]nv\w*)\(\s*\"([A-Z][A-Z0-9_]*)\""
)
TS_READ = re.compile(
    r"process\.env(?:\?)?\.([A-Z][A-Z0-9_]*)"
    r"|process\.env\[\s*[\"']([A-Z][A-Z0-9_]*)[\"']"
)
PY_READ = re.compile(
    r"os\.(?:getenv|environ\.get)\(\s*[\"']([A-Z][A-Z0-9_]*)[\"']"
    r"|os\.environ\[\s*[\"']([A-Z][A-Z0-9_]*)[\"']"
)


def is_non_config(path: Path) -> bool:
    p = str(path).replace("\\", "/")
    return any(marker in p for marker in NON_CONFIG)


def iter_files(*suffixes: str):
    for path in ROOT.rglob("*"):
        if not path.is_file() or SKIP_DIRS.search(str(path)):
            continue
        if path.suffix in suffixes and not is_non_config(path):
            yield path


def pydantic_env_names(path: Path) -> list[str]:
    """Env names a pydantic-settings class declares (env_prefix + field, or alias)."""
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        bases = {b.id for b in node.bases if isinstance(b, ast.Name)}
        if not bases & {"BaseSettings", "BaseAppSettings"} and not any(
            isinstance(b, ast.Attribute) for b in node.bases
        ):
            continue
        prefix = ""
        for stmt in node.body:
            targets = getattr(stmt, "targets", []) or [getattr(stmt, "target", None)]
            if any(isinstance(t, ast.Name) and t.id == "model_config" for t in targets if t):
                for kw in getattr(stmt.value, "keywords", []):
                    if kw.arg == "env_prefix" and isinstance(kw.value, ast.Constant):
                        prefix = kw.value.value
                if isinstance(stmt.value, ast.Dict):
                    for k, v in zip(stmt.value.keys, stmt.value.values):
                        if isinstance(k, ast.Constant) and k.value == "env_prefix":
                            prefix = v.value
        for stmt in node.body:
            if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
                continue
            field = stmt.target.id
            if field.startswith("_") or field == "model_config":
                continue
            # The Settings container holds sub-settings under lowercase names;
            # only an UPPERCASE field is an env var.
            if not field.isupper():
                continue
            alias = None
            if isinstance(stmt.value, ast.Call):
                for kw in stmt.value.keywords:
                    if kw.arg == "validation_alias" and isinstance(kw.value, ast.Constant):
                        alias = kw.value.value
            names.append(alias or (prefix + field).upper())
    return names


def violations(name: str) -> list[str]:
    problems = []
    if name in WHITELIST:
        return problems
    if not name.startswith("AGENTAREA_"):
        return [f"missing the AGENTAREA_ prefix (add it, or whitelist it as a foreign contract)"]
    if "__" in name:
        problems.append("uses '__', which is reserved for pydantic's nested delimiter")
    if len(name) > MAX_LEN:
        problems.append(f"is {len(name)} chars, over the {MAX_LEN}-char budget")
    if UNIT_SUFFIX.search(name) and name not in UNIT_SUFFIX_ALLOWED:
        problems.append("puts the unit in the name; durations carry it in the value (e.g. '30s')")

    rest = name[len("AGENTAREA_"):]
    parts = rest.split("_")
    if name not in NO_DOMAIN:
        domain = parts[0]
        if domain not in DOMAINS:
            problems.append(
                f"uses domain '{domain}', which is not in the closed list "
                f"({', '.join(sorted(DOMAINS))})"
            )
        elif len(parts) > 1 and parts[1] == domain:
            problems.append(f"repeats the domain '{domain}' after the prefix")
        elif len(parts) - 1 > MAX_SEGMENTS_AFTER_DOMAIN:
            problems.append(
                f"has {len(parts) - 1} segments after the domain, over the "
                f"{MAX_SEGMENTS_AFTER_DOMAIN} allowed"
            )
    return problems


def main() -> int:
    found: dict[str, set[str]] = {}

    def record(name: str, path: Path):
        found.setdefault(name, set()).add(str(path.relative_to(ROOT)))

    for path in iter_files(".py"):
        for name in pydantic_env_names(path):
            record(name, path)
        for match in PY_READ.finditer(path.read_text()):
            record(next(g for g in match.groups() if g), path)

    for path in iter_files(".go"):
        for match in GO_READ.finditer(path.read_text()):
            record(match.group(1), path)

    for path in iter_files(".ts", ".tsx", ".js", ".mjs"):
        for match in TS_READ.finditer(path.read_text()):
            record(next(g for g in match.groups() if g), path)

    failures = []
    for name in sorted(found):
        for problem in violations(name):
            failures.append((name, problem, sorted(found[name])[:2]))

    if failures:
        print(f"{len(failures)} environment variable naming violation(s):\n")
        for name, problem, where in failures:
            print(f"  {name}")
            print(f"      {problem}")
            print(f"      seen in: {', '.join(where)}")
        print("\nScheme: AGENTAREA_<DOMAIN>_<KEY>, <= 34 chars, unit in the value.")
        print("A name owned by a third party belongs in WHITELIST in this file.")
        return 1

    print(f"env naming OK — {len(found)} variables checked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
