# Unified MCP runtime: one base image, immutable package images, stateless protocol

Status: draft for review · 2026-09-24, revised 2026-09-25 (protocol 2026-07-28,
base image), revised 2026-09-28 (images in a registry, mcp-base)

## Problem

Container-backed MCP servers ran in two shapes before this work, and both are
wrong for what comes next (vibe-coded MCP Apps, user MCP servers, an
enterprise cloud):

- `command` instances ran `agentarea/mcp-bridge:latest`, which spawns
  `npx -y <pkg>` / `uvx <pkg>` at start (`internal/container/manager.go`,
  `internal/providers/backend_provider.go`). Every cold start downloads the
  package from npm/PyPI and the container needs egress to package registries.
  On Docker Desktop, the first successful tool call through the governed proxy,
  gateway and container takes 18.5–22 s cold and 0.5–0.6 s warm.
- `docker` instances run an arbitrary image.

Admission was two operator-level allowlists (`MCP_ALLOWED_COMMAND_PACKAGES`,
`MCP_ALLOWED_IMAGE_REPOSITORIES`) shipping six demo packages and two images.
They refused every other catalog server — 2203 distinct `npx`/`uvx` commands in
the dev catalog — and every server a member added. Step A removes both.

Every hop also speaks the 2025 handshake protocol, which is what keeps scale to
zero from being invisible:

- Platform clients open a session and send `initialize` before every list or
  call (`libs/mcp/.../service.py:1122-1166`, `mcp_aggregator.py:145-195`,
  `verification.py:222-253`), so every tool call pays for an extra round trip.
- The bridge hands every client the same fake `Mcp-Session-Id`, forwards all
  their `initialize` requests into one shared stdio session, and holds GET
  streams open with keepalives (`bridge.py:176-267`). An open GET keeps the
  gateway lease alive and blocks reclamation (`gateway.go:331-362`).
- The platform's own MCP endpoints authenticate follow-up requests through a
  per-process map from session id to user
  (`agents_sdk/mcp_server/auth.py:157-241`), which breaks when a second API
  replica serves the same client.

## Decision

1. Every container-backed MCP server runs as an immutable OCI image. A
   package import produces one image for one exact `package@version`; a server
   that needs operating-system packages uses a custom image built from the base.
2. The runtime base is `agentarea/agentarea-mcp-base`, built from
   `mcp-servers/mcp-base/`. It replaces `agentarea/mcp-bridge` for `command`
   connections in the first migration step. `npx` and `uvx` still download
   packages at start during that step.
3. A package image is the mcp-base layers plus one layer containing the
   installed package and its dependencies. The image is shared by every
   workspace, discovered by a `package@version` tag and run by an immutable
   digest reference.
4. After import, the connection is an ordinary `docker` connection. Its
   invocation arguments and environment stay on the connection; the package
   image contains the installed files, not workspace-specific invocation data.
5. Every hop we own speaks MCP 2026-07-28 and is stateless. 2025-era clients
   and servers keep working through the SDKs' era negotiation.

The whole-stack measurement on Docker Desktop is 4.7–5.0 s cold and 0.3–0.4 s
warm for a package already present in a package image, versus 18.5–22 s cold
and 0.5–0.6 s warm for the current `npx` path. The package image removes npm or
PyPI from the server start path; the server still keeps the internet access it
needs for its external API.

### Why not the alternatives

- **Use one image per package or server (decision).** The registry gives the
  platform immutable digests, shared base layers, node-local caching, image
  garbage collection and existing signing, SBOM and scanning workflows. The
  same image contract works with Kubernetes and managed container runtimes.
- **Keep `npx` at start and add a shared npm cache.** Start still depends on
  package-registry egress, cache contents are mutable, and a cache does not
  give every workspace an immutable runtime identity.
- **Put tarballs in S3 and fetch and extract them at start.** A bare Docker run
  measured a median 6.4 s when the package was already in an image layer and
  7.6 s when the same package was downloaded and extracted at start: about
  1.2 s is extraction alone. S3 would also require the platform to reimplement
  node-local caching, image-style garbage collection, authorization and
  lifecycle handling. A registry may use S3 for blob storage without putting
  extraction on every start.
- **Use SnapStart-like snapshots.** A snapshot captures a heavier runtime,
  complicates invalidation and can capture credentials or other secrets in
  memory. The image is the durable unit; a warm pool or snapshot mechanism can
  be evaluated separately.

## Base image

`agentarea/agentarea-mcp-base` replaces `agentarea/mcp-bridge`. It contains:

- Node 22, Python 3.12, `uv`/`uvx` and `git`.
- Python `mcp` 2.2.0 for the bridge.
- TypeScript MCP SDKs pinned at 2.0.0: `@modelcontextprotocol/server`,
  `@modelcontextprotocol/node`, `@modelcontextprotocol/express`,
  `@modelcontextprotocol/ext-apps` and `zod`. They live under
  `/opt/mcp-base/node/node_modules`, so an MCP App built on this image ships
  only its own files and can link to the image SDKs.
- UID 10001 and Python bytecode precompiled at build time.
- The entrypoint `python -m mcp_base <command> [args...]`, which runs the
  stdio command behind the bridge.

The bridge opens port 8080 with `/mcp` and `/health` only after the child has
answered `initialize`. It serves MCP 2026-07-28 and 2025-era clients from the
same endpoint and mints no `Mcp-Session-Id`. It exits if the child dies or if
the child does not initialize before `MCP_BASE_STARTUP_TIMEOUT` (default
300 seconds).

The image does not include Chromium system libraries such as `libnss3`,
`libgbm`, `libatk`, `libxkbcommon` or `libasound`. A server that needs a browser
or another native system dependency uses a custom image built `FROM
agentarea/agentarea-mcp-base`; the import reports this requirement when its
offline smoke test cannot start.

The manager uses the image named by `MCP_BASE_IMAGE`, defaulting to
`agentarea/agentarea-mcp-base:latest`; the chart exposes the same choice as
`mcpManager.mcpBase.image`.

## Images per package

The import service builds one image for each exact `package@version`. It appends
the installed package directory as one layer on top of the mcp-base image and
pushes the result to the configured build repository. The conventional tags are
`npm/<pkg>:<version>` and `pypi/<pkg>:<version>`. Tags answer "already built?"
with a registry manifest lookup; connections store and run the resulting
`sha256` digest.

A converted connection looks like this:

```json
{
  "type": "docker",
  "image": "<build-repo>/npm/<pkg>@sha256:<digest>",
  "port": 8080,
  "command": ["<entry>", "<args>"],
  "env": {"<name>": "<value>"}
}
```

The `command` and `env` values above belong to the connection. They are not
baked into the shared package image, so every workspace can invoke the same
package image with its own arguments and credentials. The image digest is the
runtime identity used for admission, protocol verdict caching and tool-list
cache invalidation.

MCP Apps later use the same layout: mcp-base plus an app layer of a few
kilobytes containing the app files and a symlink to the pinned SDKs.

## Build/import

The import runs once for a `package@version` in a one-shot mcp-base container.
The container has network access for installation and the isolation tier the
resulting server will receive.

1. Resolve the invocation to an exact version and entrypoint. `npx -y <pkg>
   [args]` becomes `npm install --omit=dev <pkg>@<version>`; `uvx <pkg> [args]`
   becomes `uv pip install --target … <pkg>==<version>`. The resolver keeps the
   invocation arguments on the connection.
2. Install into a package directory. The import observes the whole filesystem;
   it does not redirect caches or hide install-time side effects. If the
   install writes outside that directory, the import fails and reports every
   detected path. For example, a package that downloads Chromium into
   `~/.cache` and needs `libnss3` is reported instead of silently moving the
   cache.
   The build container then streams a `tar` of that directory to the manager
   over a one-time token; it never receives registry credentials.
3. Resolve the package's executable and collect the installed files as one
   layer. The trusted manager appends that layer to mcp-base with
   go-containerregistry `mutate.Append`; it does not need a Docker daemon or
   elevated privileges.
4. Run the resulting image with network access disabled. The import succeeds
   only when `initialize` and `tools/list` both succeed. This catches servers
   that download data at start or require an operating-system library that is
   not in mcp-base. The report names the detected dependency and directs the
   user to a custom image `FROM agentarea/agentarea-mcp-base` or a ready image
   from the catalog.
5. Push the image from the trusted manager to the build repository under the
   package/version tag. The manager records the digest returned by the registry
   and writes that digest into the connection. A registry manifest lookup by
   tag skips the import when the exact package version is already present.

A registry push failure fails the new import and leaves existing connections
unchanged. Build failures never interrupt running connections that already use
an immutable image digest.

Catalog JSON continues to describe the source invocation as `npx` or `uvx`.
Connection creation resolves that invocation, checks the package/version
manifest, and imports it only when needed. A catalog pre-import job may build
current catalog versions before the first connection.

## Admission

There is no allowlist of packages or images. Catalog servers and servers a
member adds are the same kind of code — third-party packages and images nobody
on our side reviewed — so neither origin earns a weaker boundary than the other.

Risk is carried by where and how the workload runs, and that is a property of
the deployment, not of the connection:

- Our cloud runs every MCP workload on the remote data plane, a dedicated host
  where every pod gets `runtimeClassName: gvisor` and the `untrusted` tier,
  enforced by the `agentarea-mcp-requires-gvisor` admission policy.
- A self-hosted cluster chooses `mcpManager.runtimeClass` and
  `mcpManager.isolationTier`. With the default runtime (runc) every connected
  package shares the node's kernel; the chart says so where the choice is made.
- Docker Compose runs MCP on the host kernel at the `standard` tier.

What may be imported in step B is an import policy stored as a platform
setting. The OSS default allows any public npm or PyPI package. A package image
is referenced by digest after import; a mutable tag is used only for discovery.

## Delivery and reliability

The registry is on the start path only for the first pull on a node. Kubelet or
containerd caches the base and package layers per node, so a second start on
the same node pulls nothing and shared mcp-base layers are reused. Standard
image garbage collection manages unused layers. Lazy pulling through SOCI,
eStargz or Nydus is available as a later optimization, not a dependency of
this design.

The chart pre-pulls mcp-base on every node with a DaemonSet. The Docker backend
pulls it when the manager starts. The demand gateway waits for the workload's
port to accept connections after starting it; this is also the behavior of the
remote data plane. A package image is referenced by digest, so a tag moving in
the registry cannot change an existing connection.

The registry is a managed registry or Zot with its S3 storage driver, deployed
as stateless replicas. Staging already runs Zot. OCI registries provide the
existing hooks for signing, SBOM publication and vulnerability scanning, and
managed runtimes such as Cloud Run, Fargate and Lambda container images consume
the same format. Build failures and registry outages affect only new starts;
connections already running from pulled images continue to run.

Docker Compose uses the local Docker daemon as its single-host image store and
does not require a registry. The manager loads completed images into that
store and uses their local digest. Kubernetes and managed runtimes use the
configured registry.

## Network

Starting a server no longer depends on npm or PyPI, but the server keeps the
internet access it has today. Most MCP servers exist to call an external API
(Telegram, GitHub, Slack), and the instance egress policy
(`templates/agentarea-mcp-manager/instance-networkpolicy.yaml`) allows DNS and
the public internet while denying cluster-internal and link-local ranges.
Import has package-registry access; runtime start does not. Per-server egress
allowlists (only `api.telegram.org` for a Telegram server) are a separate
governance feature and out of scope here.

## Protocol: 2026-07-28, stateless end to end

The target: any request can land on a freshly started container, and a
container can be reclaimed between any two requests, with added latency as the
only visible effect.

| Hop | Today | After |
|---|---|---|
| Platform clients: agent tool calls, verification, aggregator | `mcp` 1.28 `ClientSession.initialize()` before every operation | `mcp` 2.x `Client` over `streamable_http_client` with an `httpx2` client, era verdict cached (below) |
| Webapp Apps host | TS SDK 2.0 in its default `legacy` negotiation | `versionNegotiation: { mode: 'auto' }`; declares `extensions["io.modelcontextprotocol/ui"]` |
| Platform MCP endpoints: harness `/mcp/clients/{id}`, agents SDK `create_mcp_server` | FastMCP, `stateless_http=True`, follow-ups authenticated by session id | `MCPServer`, `stateless_http=True`, bearer checked on every request; session map removed |
| Image-backed HTTP servers | — | SDK 2.x: TS `createMcpHandler(factory, { legacy: 'stateless' })`, Python `streamable_http_app(stateless_http=True)` |
| stdio packages | bridge: one shared session, fake session id, keepalive GET | stdio bridge (below) |
| Governed proxy `mcp_proxy.py` | parses the body of `tools/call` for policy | also refuses a request whose `Mcp-Method`/`Mcp-Name` headers disagree with the body |
| Manager gateway | per-request lease, HTTP-level usage | usage events carry `Mcp-Method` and `Mcp-Name` when present: per-tool metering without parsing bodies |

**Era verdict cache.** `auto` negotiation probes with `server/discover` on
every connect, which is one extra round trip per call against a 2025 server.
The platform stores the verdict per instance and runtime identity (image digest
or command) in Redis:

- modern: the saved `DiscoverResult`; the next call connects with
  `mode="2026-07-28", prior_discover=saved`, so a tool call is one HTTP
  request;
- legacy: the next call connects with `mode="legacy"` and skips the probe;
- the entry is dropped when the runtime identity changes or a call fails with
  `-32022` (unsupported protocol version) or "method not found".

**Legacy clients.** Claude Code, Codex and older SDK clients that still speak
2025-11-25 are served from the same endpoints: both SDKs route by the
`MCP-Protocol-Version` header, and stateless serving mints no session. What
they lose is server-initiated requests (sampling, elicitation, roots) on the
2025 leg. A search of the platform found no server using them. Interactive
input uses the era-portable form (`Resolve`/`Elicit` in Python,
`input_required` results in TS), which works on 2026 connections.

**Header consistency.** 2026 clients send `Mcp-Method` and `Mcp-Name` on every
Streamable HTTP request. Governance keeps deciding on the parsed body; the
proxy refuses a mismatch so the gateway can meter on headers it did not parse.
A 2025 request has no such headers and is metered per HTTP request, as today.

**Tool lists.** The Redis tool-list cache (`tool_list_cache.py`, fixed 60 s)
is keyed by instance and runtime identity, so a new image never reads the
previous version's list, and honours the server's `ttlMs` when it sends one.
Verification fills it.

**Change notifications.** Platform clients do not open `subscriptions/listen`
streams; list changes reach them through the cache TTL. A client that opens one
holds a gateway lease for as long as it stays open, exactly like an open
request.

## Stdio bridge

The mcp-base bridge uses Python `mcp` 2.2.0:

- Inward: one `ClientSession` to the child over stdio, initialized once at
  start with the handshake stdio packages speak.
- Outward: a low-level `Server` whose handlers forward tools, resources,
  prompts and completions to the child, served with
  `streamable_http_app(stateless_http=True)`. 2026 and 2025 clients are both
  served; no session id is minted. Capabilities mirror the child's
  `InitializeResult`.
- The child's `list_changed` notifications are published on the SDK's
  subscription bus, which delivers them to `subscriptions/listen` streams.
- The child's server-initiated requests (sampling, elicitation, roots) are
  answered with an error: a stateless endpoint has no channel to forward them.
  Packages that depend on them do not work behind the bridge.

The bridge opens port 8080 with `/mcp` and `/health` only after the child has
answered `initialize`. It exits non-zero if the child dies or if initialization
does not complete within `MCP_BASE_STARTUP_TIMEOUT`, which defaults to 300
seconds. The gateway therefore never treats a listening port as healthy before
the child has completed its handshake.

The child is one process with its own state, so a bridge-backed instance stays
at one replica.

## Migration
Phase 1 shipped alone: it changes the protocol and nothing about how containers
start.

1. Python `mcp` 1.28 → 2.x and `fastmcp` 3 → 4 (the e2e fixture needs `mcp`
   2). Objects handed to the SDK become `httpx2`; other `httpx` use stays.
   Migrate the seven call sites, remove the session map in `auth.py`, and
   rewrite tests that pin `Mcp-Session-Id` or `initialize`.
2. Era verdict cache in the MCP service and aggregator.
3. Webapp host: `auto` negotiation and the UI extension capability.
4. Governed proxy: header/body consistency.
5. Demo servers: `createMcpHandler(..., { legacy: 'stateless' })`.
6. Bridge: answer `server/discover` itself with "method not found" instead of
   forwarding it. Some stdio servers exit on any request before `initialize`,
   so a probe that reaches a fresh child could kill it; the answer makes
   `auto` clients fall back to the handshake.
7. Gateway: usage events carry `Mcp-Method` and `Mcp-Name`. Requests reach the
   gateway either through the governed proxy, which checked the headers, or
   from platform clients, which set them from the body.

### Step A: mcp-base for command connections (now)

1. Ship `agentarea/agentarea-mcp-base` with the stdio bridge and the pinned
   runtime dependencies.
2. Use it instead of `agentarea/mcp-bridge` for `command` connections. Keep
   `npx`/`uvx` at start, so package-registry egress remains a migration-only
   dependency.
3. Keep the manager's demand gateway waiting for the workload port after it
   starts; the mcp-base bridge opens that port only after `initialize`.
4. Because the port now opens late, the Docker health monitor treats a
   container that has never answered as starting, not failed, until
   `STARTUP_TIMEOUT`. An answer recorded for an earlier container under the
   same name does not count.
5. The platform client and the governed proxy repeat requests the gateway
   answers "workload is starting" (`X-AgentArea-MCP-Starting`), as the webapp
   used to do itself.
6. The gateway reads the request body before it waits on a cold start, so the
   server's 30 s read deadline cannot fail a request held through an install.
7. mcp-base exits when its stdio server dies, so the gateway replaces a stopped
   workload on the next request and fails a start as soon as the workload
   stops, instead of waiting out the startup timeout either way.
8. The bridge pings the child without a timeout. Cancelling a late ping sent a
   `notifications/cancelled` that crashed 1.x Python servers blocked in a
   synchronous call (mcp-server-fetch runs `npm install` on its first fetch).
9. Remove `MCP_ALLOWED_COMMAND_PACKAGES`, `MCP_ALLOWED_IMAGE_REPOSITORIES` and
   the check that refused package-registry and proxy variables in a
   connection's environment; that check existed only to keep an allowlist
   entry meaning one package from one registry, and it also blocked private
   npm registries.

Under the manager's default limits (1 CPU, 512 MB) the first agent tool call
on a cold workload measured 50–150 s for `npx` and `uvx` packages on Docker
Desktop, and once 304 s for a `uvx` install, at the edge of the 5 min startup
budget; the same install without limits took 21 s. Every such call is longer
than the Python SDK's 10 s `server/discover` probe, so the first connection
after a cold start falls back to 2025-11-25 and its era verdict is cached as
legacy; warm connections without a verdict negotiate 2026-07-28. Step B's
package images take the install off the start path.

### Step B: registry import and conversion

1. Add the build repository and the package import job. Build one image per
   `package@version`, run the offline smoke test, append the package layer with
   go-containerregistry and push it from the trusted manager.
2. At connection creation, resolve catalog `npx`/`uvx` JSON to the exact package
   version, look up its tag, and import it when absent. Keep invocation
   arguments and environment on the connection.
3. Convert successful `command` connections and catalog entries to ordinary
   `docker` connections with a build-repository image digest. A connection
   that has not imported successfully stays on `command` and reports the
   import failure.
4. Pre-pull mcp-base: a chart DaemonSet on every Kubernetes node, and the
   Docker backend when the manager starts.

### Step C: remove command mode

Once no connection uses `command`, remove `command` mode. The old
`agentarea/mcp-bridge` and both admission allowlists were already removed in
step A; the mcp-base stdio bridge remains for package images that use it.

## Error handling

| Failure | Where | Result |
|---|---|---|
| Install writes outside the package directory | import job | Import fails before push; the report lists the detected paths and points to a custom image when those writes are a system dependency |
| Offline smoke test cannot complete `initialize` and `tools/list` | import job | Import fails before push; the report names the missing download, command or OS library |
| Registry push fails | trusted manager import path | The new import fails and no connection receives a digest; existing connections remain unchanged |
| Image manifest or digest is unavailable | registry or manager | Demand fails before a workload starts; the image reference and registry error are logged |
| Child fails `initialize` | stdio bridge | Exits non-zero before opening port 8080; failed start includes the child's stderr tail |
| Child dies after initialization | stdio bridge | Exits non-zero; the gateway records a failed workload and does not keep the port healthy |
| Child does not initialize before `MCP_BASE_STARTUP_TIMEOUT` | mcp-base bridge | Exits non-zero before opening `/mcp` or `/health`; the timeout and configured value are reported (default 300 seconds) |
| `Mcp-Method`/`Mcp-Name` disagree with the body | governed proxy | HTTP 400, JSON-RPC error `-32020`, not forwarded |
| Cached verdict stale (`-32022`, method not found) | platform client | Verdict dropped, one reconnect with `auto` |

## Testing

- **Go:**
  - A package image is run by digest, and a moved tag does not change what an
    existing connection runs.
  - The manager appends the installed package layer with go-containerregistry
    and pushes it without a Docker daemon or registry credentials in the build
    container.
  - Import reports every write outside the package directory, rejects a failed
    offline `initialize`/`tools/list` smoke test, and leaves existing
    connections unchanged when a registry push fails.
  - A workload that stops, or never listens, is replaced or failed without
    waiting out the startup timeout.
  - Usage events carry `Mcp-Method`/`Mcp-Name` when the request has them.
- **Base image and stdio bridge:**
  - A child that answers `initialize` causes `/mcp` and `/health` on port 8080
    to accept connections; before that handshake the port stays closed.
  - A child that dies or exceeds `MCP_BASE_STARTUP_TIMEOUT` exits non-zero and
    leaves the port closed.
  - A 2026 client and a 2025 client call the same tool against one child; no
    response carries `Mcp-Session-Id`.
- **Platform:**
  - The era verdict: a modern entry connects with no probe, a legacy entry
    skips it, and `-32022` drops it.
  - The proxy refuses a `tools/call` whose `Mcp-Name` differs from
    `params.name`.
  - The harness endpoint accepts a follow-up request on a different API
    replica (no session map).
- **End to end and measurement baseline:**
  - With the container reclaimed between two tool calls, both succeed and the
    second one pays only the new cold start.
  - Import `@modelcontextprotocol/server-customer-segmentation`, create the
    connection from its package image, block npm/PyPI egress, and complete the
    first tool call through the governed proxy, gateway and container.
  - On Docker Desktop, record the first successful tool call as 4.7–5.0 s cold
    and 0.3–0.4 s warm for the package image, compared with 18.5–22 s cold and
    0.5–0.6 s warm for the current `npx` path.
  - In a bare Docker run, record the package image median at 6.4 s and the same
    package downloaded and extracted at start at 7.6 s; the difference is about
    1.2 s of extraction.
  - An MCP App importing the image SDKs starts in 1.4–2.0 s in a bare Docker
    run.
  - The Apps page still renders the app over a 2026 connection.

## Out of scope

- A warm pool of unassigned runtime pods.
- SnapStart-like runtime snapshots.
- Lazy pulling through SOCI, eStargz or Nydus.
- Per-server egress allowlists.
- Per-workspace policy on which packages or images may be connected.
- MCP Apps publishing, definitions, versions and app configuration; the later
  app-image work builds on this runtime.
