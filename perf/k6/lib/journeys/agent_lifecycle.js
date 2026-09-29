// Create -> read -> update (attach a skill, and an MCP connection if one is
// already sitting there from a connection_lifecycle run) -> delete.
//
// The skill is created here, disposably, so this journey doesn't depend on
// skill_lifecycle having run first. The MCP attach is opportunistic: an
// agent's `tools` array references an MCP instance BY NAME, not id (see
// agentarea-platform/libs/bundles/.../installer.py — McpToolConfig(name=mcp.name)),
// so if a k6-prefixed instance already exists (from connection_lifecycle),
// this reuses it instead of creating a second one — "if cheap" means "don't
// do the extra network-verifying create just for this".
import { check, group } from "k6";
import { BASE_URL, WORKSPACE } from "../config.js";
import { get, postJson, patchJson, del } from "../http.js";
import { assertWriteAllowed } from "./guard.js";
import { resourceName, isOurs } from "./naming.js";
import { createSkill, deleteSkill } from "./skill_lifecycle.js";
import { tag } from "./tags.js";

const ws = (suffix) => `${BASE_URL}/v1/workspaces/${encodeURIComponent(WORKSPACE)}${suffix}`;

function findOurMcpInstanceName() {
  const res = get(ws("/mcp-server-instances/"), "list_for_attach", tag("agent_lifecycle", "list_for_attach"));
  if (res.status !== 200) return null;
  const instances = res.json() || [];
  const ours = instances.find((i) => isOurs(i.name));
  return ours ? ours.name : null;
}

export const agentLifecycle = {
  name: "agent_lifecycle",
  run: () => {
    assertWriteAllowed("agent_lifecycle");
    group("journey: agent_lifecycle", () => {
      const name = resourceName("agent");
      const createRes = postJson(
        ws("/agents/"),
        { name, tools: [] },
        "create",
        tag("agent_lifecycle", "create")
      );
      check(createRes, { "agent create -> 200/201": (r) => r.status === 200 || r.status === 201 });
      if (createRes.status >= 300) return;
      const agent = createRes.json();

      const readRes = get(ws(`/agents/${agent.id}`), "read", tag("agent_lifecycle", "read"));
      check(readRes, { "agent read -> 200": (r) => r.status === 200 });

      const skill = createSkill();
      const mcpName = findOurMcpInstanceName();
      const tools = mcpName ? [{ type: "mcp", name: mcpName }] : [];
      const updateBody = tools.length ? { tools } : {};
      if (skill && skill.id) updateBody.skill_ids = [skill.id];

      const updateRes = patchJson(
        ws(`/agents/${agent.id}`),
        updateBody,
        "update",
        tag("agent_lifecycle", "update")
      );
      check(updateRes, { "agent update -> 200": (r) => r.status === 200 });

      const deleteRes = del(ws(`/agents/${agent.id}`), "delete", tag("agent_lifecycle", "delete"));
      check(deleteRes, { "agent delete -> 200/204": (r) => r.status === 200 || r.status === 204 });

      deleteSkill(skill && skill.id);
    });
  },
};
