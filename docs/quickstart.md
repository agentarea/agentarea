---
title: Run AgentArea locally
type: tutorial
description: "Start the full development stack with Docker Compose and reach a working dashboard and API."
prerequisites: []
related:
  - /how-it-works
  - /guides/agents/create-and-configure
  - /self-host/requirements
  - /self-host/troubleshooting
last_updated: 2026-09-07
---

By the end you will have the platform running on your machine: an API on port
8000, a dashboard on port 3000, and the supporting services — Postgres, Valkey,
Temporal, the Go MCP manager, object storage and Ory Kratos — running alongside
them.

<Info>
This is the development stack, tuned for hot reload and throwaway credentials.
For a real deployment, start at [requirements](/self-host/requirements).
</Info>

## Before you start

| You need | Check it with |
|---|---|
| Docker with Compose v2 | `docker compose version` prints `v2.x` |
| Git | `git --version` |
| Node.js 20+ and pnpm | `node -v` and `pnpm -v` |
| 16 GB RAM, 20 GB free disk | The stack defines 22 services — 5 one-shot migration jobs, 17 long-running |

## Start the stack

<Steps>
  <Step title="Clone the repository">
    ```bash
    git clone https://github.com/agentarea/agentarea.git
    cd agentarea
    ```
  </Step>

  <Step title="Create the environment file">
    ```bash
    cp .env.example .env
    ```

    The defaults are development credentials and work as they are. Do not reuse
    this file anywhere real — see [configuration](/self-host/configuration) for
    what each value does.
  </Step>

  <Step title="Start the services">
    ```bash
    make up-dev
    ```

    <Warning>
    Despite its help text, `make up-dev` runs `docker compose up` **in the
    foreground**, without `-d`. It holds the terminal. Open a second terminal for
    the next steps, or run `docker compose -f docker-compose.dev.yaml up -d`
    yourself.
    </Warning>

    First run pulls and builds images, which takes several minutes. The stack is
    ready when the API answers.
  </Step>

  <Step title="Check the API">
    ```bash
    curl http://localhost:8000/health
    ```

    ```json
    {"status":"healthy","timestamp":"2026-09-07T10:14:52.118442"}
    ```

    The MCP manager has its own health endpoint:

    ```bash
    curl http://localhost:7999/health
    ```

    Interactive API documentation is at `http://localhost:8000/docs`.
  </Step>

  <Step title="Start the dashboard">
    The dev stack does **not** include the frontend — it is commented out in
    `docker-compose.dev.yaml` so you can run it with hot reload. In a second
    terminal:

    ```bash
    cd agentarea-webapp
    pnpm install
    pnpm dev
    ```

    <Check>
    Open `http://localhost:3000`. Ory Kratos redirects login and consent to this
    exact origin, so use `localhost:3000` rather than `127.0.0.1`.
    </Check>
  </Step>
</Steps>

## What you have

The services you will actually interact with:

| Service | Port | What it is |
|---|---|---|
| API | 8000 | REST, SSE, A2A, and the platform MCP server |
| Dashboard | 3000 | The web UI, run outside Compose |
| MCP manager | 7999 | Sandbox and MCP lifecycle, Go |
| Temporal | 7233 | Workflow server; inspect with the `temporal` CLI |
| Object storage | 9000 / 9001 | RustFS, S3-compatible |
| Kratos | 4433 / 4434 | Identity, public and admin APIs |
| Mailpit | 8025 | Catches sign-up emails locally; SMTP stays internal |
| OpenFGA | 8088 / 8089 | Authorization, HTTP and gRPC |

The dev stack additionally runs Keto, OpenFGA and Hydra, which the production
Compose file does not.

## Stop the stack

<CodeGroup>

```bash Stop
make down-dev
```

```bash Stop and wipe data
make down-clean
```

</CodeGroup>

`make down-clean` also drops the volumes, so the next start is from scratch.

## Related

<Columns cols={2}>
  <Card title="How it works" icon="sitemap" href="/how-it-works">
    The request path across control and data plane. Read this before anything
    else.
  </Card>
  <Card title="Create and configure an agent" icon="robot" href="/guides/agents/create-and-configure">
    Give an agent a model and run its first task.
  </Card>
  <Card title="Troubleshooting" icon="server" href="/self-host/troubleshooting">
    When a service will not come up.
  </Card>
  <Card title="Self-host requirements" icon="server" href="/self-host/requirements">
    Running it somewhere other than your laptop.
  </Card>
</Columns>
