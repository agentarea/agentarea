"""Credentials the deployment supplies, for providers no tenant brings a key to.

A normal provider configuration stores the *name* of a secret, and that secret is
read back through ``DatabaseSecretManager``, which filters on the caller's
workspace. That scoping is correct and load-bearing for tenant keys — and it is
exactly why an operator-supplied key cannot live there. The credential belongs to
no workspace, so every workspace-scoped read of it returns None, and it would have
to be copied into each tenant's workspace to work at all. At that point the tenants
own it: it is in a table their own API writes to, and rotating it means finding
every copy.

So it is not in the database. It comes from the process environment, which means:

  * no tenant-reachable code path can read it, by construction rather than by a
    check somebody has to remember to write;
  * rotation is a Secret update and a restart, not a migration over N workspaces;
  * an open-source deployment that sets nothing simply has no platform providers,
    which is the correct default for a build that sells nothing.

The name stored on the provider configuration is a *reference*, not the key:
``api_key = "openai"`` resolves to ``PLATFORM_CREDENTIAL_OPENAI``.  # pragma: allowlist secret
"""

from __future__ import annotations

import os
import re

# Any run of characters that cannot appear in a shell environment variable name.
# Collapsed to a single underscore so "openai-eu" and "openai_eu" cannot resolve to
# two different variables that a reader would expect to be the same one.
_NON_ENV_CHARS = re.compile(r"[^A-Z0-9]+")

ENV_PREFIX = "PLATFORM_CREDENTIAL_"

# The value of ``provider_configs.managed_by`` meaning "the deployment operator
# supplies this configuration's credentials, not the tenant".
#
# It lives here, in the shared layer, rather than beside the column it describes:
# the LLM library owns the column, but the execution library has to make the same
# distinction when it decides which credential store to read, and it does not
# depend on the LLM library. One definition both can import beats two that agree
# until someone edits one of them.
MANAGED_BY_PLATFORM = "platform"


def env_var_name(reference: str) -> str:
    """The environment variable a platform credential reference resolves to.

    Exposed so an operator can be told the exact variable to set, and so the
    deployment chart and this module cannot disagree about the spelling.
    """
    slug = _NON_ENV_CHARS.sub("_", reference.strip().upper()).strip("_")
    return f"{ENV_PREFIX}{slug}"


def platform_credential(reference: str) -> str | None:
    """Resolve a platform credential reference, or None if this deployment has none.

    None is a legitimate answer twice over: a provider that authenticates with
    nothing (a local endpoint, a proxy that holds the credential itself), and a
    build where no platform provider was ever configured. Callers must not treat it
    as an error on its own — the request failing with an auth error from the
    provider is a far clearer signal than a startup check guessing which providers
    ought to need a key.
    """
    if not reference:
        return None
    value = os.environ.get(env_var_name(reference))
    if value is None:
        return None
    # A Secret rendered from an empty value arrives as "", which is not a
    # credential. Returning it would send an empty Authorization header rather
    # than none at all, and the two are different requests.
    value = value.strip()
    return value or None
