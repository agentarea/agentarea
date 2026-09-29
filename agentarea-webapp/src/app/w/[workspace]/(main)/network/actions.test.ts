import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getNetworkPeopleAccessAction,
  previewNetworkPolicyAction,
} from "./actions";

const { preview, people } = vi.hoisted(() => ({
  preview: vi.fn(),
  people: vi.fn(),
}));
vi.mock("@/lib/api", () => ({
  previewEffectivePolicy: preview,
  getNetworkPeopleAccess: people,
}));
const id = "a557769a-682f-4a54-a661-597b4e60de34";
describe("network policy preview", () => {
  beforeEach(() => preview.mockReset());
  it("validates the agent before requesting policy", async () => {
    const result = await previewNetworkPolicyAction("invalid-id");
    expect(result.data).toBeUndefined();
    expect(result.error).toBeTruthy();
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
    const { data: policy } = await previewNetworkPolicyAction(id);
    expect(preview).toHaveBeenCalledWith({ agent_id: id });
    if (!policy) throw new Error("expected a policy");
    expect(policy.tools?.denied).toEqual(["delete_*"]);
    expect(policy.tools?.allowed).toEqual(["read_*"]);
    expect(policy.approval?.requires_human_approval).toBe(true);
  });
  it("does not turn a failed or malformed response into an unrestricted policy", async () => {
    preview
      .mockResolvedValueOnce({
        error: { detail: "backend unavailable" },
        status: 503,
      })
      .mockResolvedValueOnce({
        data: { effective_policy: { tools: { denied: 42 } } },
      });
    const failed = await previewNetworkPolicyAction(id);
    expect(failed.data).toBeUndefined();
    expect(failed.error).toEqual({ detail: "backend unavailable" });
    expect(failed.status).toBe(503);
    const malformed = await previewNetworkPolicyAction(id);
    expect(malformed.data).toBeUndefined();
    expect(malformed.error).toBeTruthy();
  });
});

describe("network people access", () => {
  beforeEach(() => people.mockReset());
  it("preserves an explicit denial and an incomplete snapshot", async () => {
    people.mockResolvedValue({
      data: {
        workspace_id: "workspace",
        people: [{ user_id: "member" }],
        access: [
          {
            user_id: "member",
            agent_id: id,
            allowed: false,
            reason: "policy denial",
          },
        ],
        complete: false,
        total_people: 101,
        total_agents: 1,
        decision_source: "agent_edge_admission",
      },
    });
    const { data: response } = await getNetworkPeopleAccessAction();
    if (!response) throw new Error("expected people access");
    expect(response.access[0].allowed).toBe(false);
    expect(response.complete).toBe(false);
    expect(people).toHaveBeenCalledWith();
  });
  it("does not turn admin or service failures into an empty directory", async () => {
    people.mockResolvedValue({ error: { detail: "forbidden" }, status: 403 });
    const result = await getNetworkPeopleAccessAction();
    expect(result.data).toBeUndefined();
    expect(result.error).toEqual({ detail: "forbidden" });
    expect(result.status).toBe(403);
  });
  it("rejects malformed permission decisions", async () => {
    people.mockResolvedValue({
      data: {
        workspace_id: "workspace",
        people: [],
        access: [
          { user_id: "member", agent_id: id, allowed: "yes", reason: "wrong" },
        ],
        complete: true,
        total_people: 0,
        total_agents: 1,
      },
    });
    const result = await getNetworkPeopleAccessAction();
    expect(result.data).toBeUndefined();
    expect(result.error).toBeTruthy();
  });
  it("preserves an unknown directory total with a verified owner", async () => {
    people.mockResolvedValue({
      data: {
        workspace_id: "workspace",
        people: [{ user_id: "owner" }],
        access: [],
        directory_status: "disabled",
        total_people: null,
        total_agents: 0,
        complete: false,
      },
    });
    const { data: result } = await getNetworkPeopleAccessAction();
    if (!result) throw new Error("expected people access");
    expect(result.total_people).toBeNull();
    expect(result.people[0].user_id).toBe("owner");
    expect(result.directory_status).toBe("disabled");
    expect(result.complete).toBe(false);
  });
});
