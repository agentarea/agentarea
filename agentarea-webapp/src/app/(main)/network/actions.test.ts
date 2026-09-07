import { beforeEach, describe, expect, it, vi } from "vitest";
import { previewNetworkPolicyAction } from "./actions";

const { preview } = vi.hoisted(() => ({ preview: vi.fn() }));
vi.mock("@/lib/api", () => ({ previewEffectivePolicy: preview }));
const id = "a557769a-682f-4a54-a661-597b4e60de34";
describe("network policy preview", () => {
  beforeEach(() => preview.mockReset());
  it("validates the agent before requesting policy", async () => {
    await expect(previewNetworkPolicyAction("invalid-id")).rejects.toThrow(
      "Unable to load agent policy preview"
    );
    expect(preview).not.toHaveBeenCalled();
  });
  it("preserves tool restrictions and approval requirements from the resolver", async () => {
    preview.mockResolvedValue({
      data: {
        effective_policy: {
          tools: { allowed: ["read_*"], denied: ["delete_*"] },
          approval: { requires_human_approval: true },
          source_policy_ids: ["workspace-rule"],
        },
      },
    });
    const policy = await previewNetworkPolicyAction(id);
    expect(preview).toHaveBeenCalledWith({ agent_id: id });
    expect(policy.tools?.denied).toEqual(["delete_*"]);
    expect(policy.tools?.allowed).toEqual(["read_*"]);
    expect(policy.approval?.requires_human_approval).toBe(true);
  });
  it("does not turn a failed or malformed response into an unrestricted policy", async () => {
    preview
      .mockResolvedValueOnce({ error: { detail: "backend unavailable" } })
      .mockResolvedValueOnce({
        data: { effective_policy: { tools: { denied: 42 } } },
      });
    await expect(previewNetworkPolicyAction(id)).rejects.toThrow(
      "Unable to load agent policy preview"
    );
    await expect(previewNetworkPolicyAction(id)).rejects.toThrow(
      "Unable to load agent policy preview"
    );
  });
});
