import { describe, expect, it } from "vitest";
import type { EgressExitResponse } from "@/api/client/types.gen";
import {
  boundEgressExit,
  egressExitUpdateSpec,
  toEgressExitOptions,
  withEgressExit,
} from "./egress-exit";

function exit(id: string, managedBy: string | null): EgressExitResponse {
  return {
    id,
    name: id,
    description: null,
    upstream_url: "https://proxy.example.com:8443",
    username: null,
    password_secret_id: null,
    via: null,
    allow_plaintext_credentials: false,
    managed_by: managedBy,
    created_by: "user",
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z",
  };
}

describe("egress exit binding", () => {
  it("binds an exit and unbinds by dropping the key", () => {
    const bound = withEgressExit({ environment: { A: "1" } }, "exit-1");
    expect(bound).toEqual({ environment: { A: "1" }, egress_exit: "exit-1" });
    expect(boundEgressExit(bound)).toBe("exit-1");

    const direct = withEgressExit(bound, null);
    expect(direct).toEqual({ environment: { A: "1" } });
    expect(boundEgressExit(direct)).toBeNull();
  });

  it("sends the stored spec back without the transport fields the API refuses", () => {
    const spec = egressExitUpdateSpec(
      {
        type: "docker",
        image: "ghcr.io/acme/mcp:1",
        port: 8000,
        environment: { A: "1" },
        env_vars: ["TOKEN"],
      },
      "exit-1"
    );
    expect(spec).toEqual({
      environment: { A: "1" },
      env_vars: ["TOKEN"],
      egress_exit: "exit-1",
    });
  });

  it("lists the workspace's own exits before the platform's", () => {
    const options = toEgressExitOptions([
      exit("platform-1", "platform"),
      exit("own-1", null),
    ]);
    expect(options.map((option) => [option.id, option.platform])).toEqual([
      ["own-1", false],
      ["platform-1", true],
    ]);
  });
});
