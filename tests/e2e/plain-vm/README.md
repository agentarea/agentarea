# Plain VM outbound data-plane E2E

This developer harness proves the first supported bring-up path:

`local Compose control plane -> outbound host agent -> existing Docker on a raw VM -> MCP HTTP`

It does not install Docker, OpenSandbox, k3s, firewall rules, or any other provider. The VM agent connects only to loopback endpoints delivered through a temporary SSH reverse tunnel.

The fixed IDs and credentials in this directory are test-only. The Compose ports bind to local loopback (`18000` for the platform API and `17999` for the MCP manager) and the Compose project has its own database volume.

The seed is intentionally non-destructive on repeated `docker compose up` runs: it never resets an enrolled node credential or makes a consumed token reusable. Use `docker compose -p agentarea-plain-vm-e2e -f tests/e2e/plain-vm/compose.yaml down -v` only when a deliberately fresh enrollment is required.

The VM config expects SSH reverse forwards at `127.0.0.1:28000` (platform) and `127.0.0.1:27999` (manager). Cleartext HTTP is accepted only because both agent URLs are loopback and `allow_insecure_development` is explicit.
