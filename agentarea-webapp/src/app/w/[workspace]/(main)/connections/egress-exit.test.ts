import { describe, expect, it } from "vitest";
import {
  boundEgressExit,
  egressExitUpdateSpec,
  withEgressExit,
} from "./egress-exit";

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
});
