---
title: "Engineering Principles"
description: "AgentArea code principles for humans and LLM coding agents"
---

# Engineering Principles

This page is the start of AgentArea's LLM wiki: a compact, durable reference for
how we want code to be written, reviewed, and extended. Treat it as the shared
contract for humans and coding agents working in this repository.

## Prefer Existing Shapes

Before adding a new pattern, find the closest existing implementation and match
it unless there is a concrete reason not to. AgentArea is a polyglot monorepo;
consistency matters more than local cleverness.

Examples:

- Collection endpoints should use the shared pagination envelope when possible:
  `PaginatedResponse[T]` with `items`, `total`, `page`, `page_size`, and
  `has_next`.
- Query parameters that represent common list behavior should reuse
  `PaginationParams` before introducing endpoint-specific pagination.
- Frontend API helpers should preserve existing call-site contracts when a
  backend response shape changes.

## Server-Side Lists First

Large collections should be paginated, counted, searched, and filtered on the
server. Client-side filtering over a full collection is acceptable only for small
or already-loaded local views.

For list endpoints:

- Include a total count that matches the active filters.
- Keep filters URL-addressable in the UI when they affect page content.
- Reset `page` when filters or search change.
- Prefer explicit query parameters such as `status`, `source_type`, `has_files`,
  or `network_scope` over overloaded free-form filters.
- Preserve backward compatibility for existing consumers when feasible, but make
  new paginated use cases opt into pagination metadata clearly.

## Compatibility Is a Feature

When changing a public or shared contract, identify all existing consumers before
editing. If a migration cannot be completed in the same change, provide a
compatibility layer with a clear path forward.

Good compatibility behavior:

- Old helper calls keep returning the same shape when downstream screens rely on
  it.
- New callers can request richer metadata without duplicating fetch logic.
- Tests cover both default behavior and the new filtered or paginated path.

## Workspace Boundaries Are Not Optional

Backend data access must preserve workspace scoping. Services and repositories
should carry `UserContext` through existing factories and scoped repositories.
Do not bypass repository filters for convenience.

When adding repository methods:

- Start from `WorkspaceScopedRepository` behavior or copy the existing workspace
  filter into custom queries.
- Apply count and list queries with the same filters.
- Keep authorization checks on mutations close to existing endpoint/service
  patterns.

## Small Changes, Fresh Evidence

Every meaningful code change should have targeted verification. Match the test
size to the blast radius:

- API behavior: focused endpoint/service tests.
- Frontend state or routing: lint plus focused UI or component checks when
  available.
- Shared contracts: tests for old and new behavior.
- Repo-wide checks: run them when available; if blocked by unrelated existing
  failures, record the blocker explicitly.

Do not claim a full typecheck or build passed when it did not. A known unrelated
blocker is still useful evidence, but it must be named.

## Documentation Is Part of the Change

Add documentation when a change establishes or clarifies a pattern that future
contributors should repeat. Prefer short, principle-level docs over verbose
implementation walkthroughs.

Document:

- Cross-cutting API shapes.
- UI routing and state conventions.
- Security, workspace, and compatibility constraints.
- Rejected alternatives that future contributors might otherwise re-explore.

## Pull Request Notes

PR descriptions should tell reviewers what changed, why it changed, and how it
was verified. Include known gaps directly rather than hiding them in comments.

For commits, use the repository's Lore protocol when writing commit messages:
state the intent first, then add trailers for constraints, rejected alternatives,
confidence, scope risk, directives, tested evidence, and known verification gaps.
