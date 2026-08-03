---
title: Open core
type: concept
summary: AgentArea's core is Apache-2.0 and self-hostable; enterprise features arrive as a separately installed Python package that registers itself through entry points, not as a fork.
prerequisites: []
related:
  - /concepts/workspaces-projects-resources
  - /concepts/control-and-data-plane
  - /concepts/governance/policy-engine
  - /concepts/governance/audit
last_updated: 2026-07-29
---

# Open core

AgentArea is open core. The platform in this repository is Apache-2.0 licensed
and runs standalone — you can self-host it, execute agents, govern tool calls,
and never install anything commercial. Enterprise capability is added by
installing an additional Python package alongside it. There is no second
codebase, no fork, and no `if enterprise:` branch in the request path.

This page describes where the line sits, how the mechanism works, and which
parts of it are wired today versus merely declared.

## The problem

Open-core products usually implement the split in one of two ways, and both age
badly.

**Forking** gives you two divergent codebases. Every bug fix lands twice or lands
once and rots in the other. Behaviour drifts until nobody can reason about the
open-source edition from the commercial one.

**Inline branching** — `if settings.ENTERPRISE:` scattered through business
logic — keeps one codebase but makes every code path conditional. The
open-source reader cannot tell which branch is live, the test matrix doubles, and
the commercial logic sits in a public repository doing nothing.

Both make the boundary implicit. The boundary should be a named seam you can
enumerate.

## How AgentArea approaches it

### The mechanism: Python entry points

Core defines extension points by name. A separately installed package advertises
factories for those names through the standard Python entry-point group
`agentarea.extensions`. At startup, core scans installed distributions and
registers whatever it finds:

```python
ENTRYPOINT_GROUP = "agentarea.extensions"

def discover_extensions() -> None:
    discovered = entry_points(group=ENTRYPOINT_GROUP)
    for ep in discovered:
        try:
            factory = ep.load()
            ExtensionRegistry.register(ep.name, factory)
            logger.info("Discovered extension: %s from %s", ep.name, ep.value)
        except Exception:
            logger.exception("Failed to load extension: %s", ep.name)
```

`discover_extensions()` runs during startup in both `apps/api` and `apps/worker`.
Entry points map a name to a **factory callable**, not to an instance, so an
implementation can construct its own dependencies rather than accepting whatever
core would have injected.

The enterprise package lives in a sibling repository, `agentarea-enterprise`, and
declares its factories the ordinary way:

```toml
[project.entry-points."agentarea.extensions"]
entitlement_guard = "agentarea_enterprise.entitlement.factory:create_plan_entitlement_guard"
egress_enforcer = "agentarea_enterprise.egress.factory:create_egress_enforcer"
```

Deploying enterprise means building an image with that package installed.
Nothing else changes: same entrypoints, same configuration, same request path.
If the package is absent, `ExtensionRegistry.has(...)` returns false and core
takes its own path.

### The extension points core looks up

| Name | Where core resolves it | Behaviour without an extension |
|---|---|---|
| `permissions` | `apps/api` and `apps/worker` startup | Falls back to the backend named by `ACCESS_CONTROL_BACKEND`, or `WorkspaceScopedPermissionService` |
| `authorization` | `apps/api` and `apps/worker` startup | `WorkspaceScopedAuthorizationService` |
| `audit_sink` | `AuditService`, after the event is persisted | Events are written to the database only |
| `entitlement_guard` | `create_governance_pipeline()`, priority 120 | The gate is not registered; the pipeline runs without it |

Two properties are worth noticing.

**Core is complete without extensions.** Each row has a working default. The
open-source edition is not a demo with holes in it.

**An extension cannot silently override an explicit choice.** `permissions` is a
selector: if an operator sets `ACCESS_CONTROL_BACKEND=openfga`, core wires
`OpenFGAPermissionService` and logs a warning that the installed extension is
being ignored. This rule exists because the earlier order — extension first —
meant an installed Keto extension shadowed a configured OpenFGA backend, so
OpenFGA never enforced while the configuration claimed it did. An extension is a
fallback for an unmade decision, never a veto over a made one.

### What DEPLOYMENT_MODE does and does not do

`DEPLOYMENT_MODE` selects `DeploymentMode.OSS` or `DeploymentMode.ENTERPRISE`
and configures a `FeatureService`. Its own docstring bounds its scope:

> This controls UI/presentation concerns only. Implementation swapping (e.g.,
> which PermissionService) is handled by the plugin extension registry, not
> feature flags.

Its properties are `show_system_entity_badge`, `system_entities_read_only_in_ui`,
`enable_usage_metering`, `show_governance_overlay`, and `enable_network_rebac`.
Setting `DEPLOYMENT_MODE=enterprise` without installing the enterprise package
changes what the interface displays. It does not add enforcement.

### Where the line currently sits

Core includes more than the original open-core plan reserved for it. Relationship
-based access control was once positioned as a commercial differentiator; it is
now in core. `OpenFGAPermissionService` and `KetoPermissionService` both ship in
`agentarea_common`, and the enterprise package's Keto `permissions` extension was
removed as redundant.

| In core | Commercial |
|---|---|
| Agent execution, tasks, Temporal workflows | Plan entitlement gating |
| Sandbox execution and MCP hosting | Usage metering and billing |
| ReBAC authorization (OpenFGA or Keto) | External audit sinks (SIEM forwarding) |
| Workspaces, projects, resources | Container egress enforcement (declared, not yet wired) |
| Governance pipeline: budget gates, security filters, observers | |
| Audit events persisted to the database | |

The line follows a rule rather than a price list: core is everything needed to
run governed agents on your own infrastructure. Commercial is what a
multi-customer or regulated operator needs on top — metering, entitlement, and
forwarding governance evidence into systems core has no business knowing about.

## Why not put everything in the open-source edition?

Then there is no business, and an unfunded platform is a worse deal for a
self-hosting team than a funded one with a boundary. The relevant question is
whether the boundary is drawn somewhere that damages the open edition, and the
test is: can you run this in production, governed, without paying? Workspace
isolation, ReBAC authorization, sandbox isolation, budget enforcement, approvals,
and audit persistence are all in core. What is held back is metering, plan
entitlement, and forwarding evidence outward.

The failure mode to watch for is a vendor moving a security control behind the
paywall after adoption. AgentArea has moved in the other direction so far, with
ReBAC arriving in core. That is one data point, not a guarantee.

## Why not feature flags instead of entry points?

A feature flag needs the code it gates to be present. Gating commercial logic
with a flag means shipping that logic in a public repository and asking a boolean
to protect it, which protects nothing and clutters the open codebase with paths
its readers cannot use.

Entry points make absence the default. The enterprise code is not in the image
unless installed, so the open-source reader sees exactly the code that runs, and
the commercial package is a normal Python distribution — versioned, pinned, and
auditable by the customer who installs it.

The costs are real. The seam has to be designed before it can be extended, so a
capability with no extension point cannot be added without changing core. Entry
points resolve at import time, which makes failures startup-time rather than
request-time. And discovery is implicit: installing a package changes runtime
behaviour with no configuration edit, which is why the startup logs name the
implementation chosen for every selector point.

## Limits

- **Not every declared extension is wired.** `egress_enforcer` is advertised by
  the enterprise package and has a core-side port
  (`agentarea_common/ports/egress_enforcer.py`, with a no-op default), but no
  core code resolves it from the registry yet. Installing enterprise does not
  currently enforce container egress.
- **Audit forwarding is best-effort.** The event is persisted first, then
  forwarded. If the sink raises, the failure is logged as a warning and the
  request proceeds. A reachable database with an unreachable SIEM loses forwarded
  events, not recorded ones — do not treat sink delivery as guaranteed.
- **`DEPLOYMENT_MODE=enterprise` alone enforces nothing.** Without the package
  installed it changes presentation only.
- **A failed extension load does not stop startup.** `discover_extensions()`
  catches per-entry-point exceptions and continues. A broken enterprise package
  yields a running server with core defaults. Check startup logs for
  `Failed to load extension` rather than assuming a clean boot means a loaded
  extension.
- **There is no license enforcement in core.** Nothing checks entitlement to run
  the platform; the commercial boundary is what the package provides, not a
  runtime check that restricts core.
- **The extension surface is small.** Four names are resolved by core today. This
  is not a general plugin API for third-party functionality.

## Related

- [Workspaces, projects, and resources](/concepts/workspaces-projects-resources) — the model both editions share
- [Control plane and data plane](/concepts/control-and-data-plane) — the boundary that makes customer-hosted execution possible
- [Policy engine](/concepts/governance/policy-engine) — the pipeline the entitlement gate joins
- [Audit](/concepts/governance/audit) — what is recorded before anything is forwarded
