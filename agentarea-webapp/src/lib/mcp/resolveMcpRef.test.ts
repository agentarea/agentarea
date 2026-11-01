import { describe, expect, it } from "vitest";
import { resolveMcpRef, type McpInstance, type McpServer } from "./resolveMcpRef";

const instance = (id: string, name: string) => ({ id, name }) as McpInstance;
const server = (id: string, name: string) => ({ id, name }) as McpServer;

const GITHUB = "00000000-0000-4000-8000-000000000001";

describe("resolveMcpRef", () => {
  it("resolves an instance id to its connection", () => {
    const res = resolveMcpRef(GITHUB, [instance(GITHUB, "github")], []);

    expect(res.status).toBe("instance");
  });

  it("never resolves a connection name to a connection, as the runtime does not", () => {
    const res = resolveMcpRef("github", [instance(GITHUB, "github")], []);

    expect(res.status).toBe("unresolved");
  });

  it("offers a name a server spec carries for connecting", () => {
    const res = resolveMcpRef(
      "GitHub",
      [instance(GITHUB, "github")],
      [server("00000000-0000-4000-8000-000000000002", "github")]
    );

    expect(res.status).toBe("server");
  });
});
