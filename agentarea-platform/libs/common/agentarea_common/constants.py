# Well-known platform identities for official/seeded content.
# Keep in sync with the duplicated copies in agentarea-operator/*.py.
PLATFORM_WORKSPACE_ID = "platform"
PLATFORM_PRINCIPAL_ID = "platform"

# The value of ``provider_configs.managed_by`` meaning "the deployment operator
# supplies this configuration's credentials, not the tenant".
#
# Here rather than beside the column it describes: the LLM library owns the
# column, but the execution library has to make the same distinction when it
# decides which workspace's secrets to read, and it does not depend on the LLM
# library. One definition both import beats two that agree until someone edits
# one of them.
MANAGED_BY_PLATFORM = "platform"

# A catalog registry's trust label (ADR-0044). The registry library stores it;
# governance policy rules name it (``registry_trust:<level>``), and neither
# library depends on the other.
REGISTRY_TRUST_LEVELS = ("official", "verified", "community", "private")

# A skill imported straight from a GitHub URL passed through no registry, so
# install rules name its source as the pseudo-registry ``registry:github`` and it
# carries the trust of an unvetted public source.
GITHUB_IMPORT_REGISTRY_ID = "github"
GITHUB_IMPORT_TRUST = "community"
