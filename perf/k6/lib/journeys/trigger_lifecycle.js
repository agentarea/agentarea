// Create a CRON trigger DISABLED -> read -> delete. Never enabled — enabling
// it would let the platform actually fire it on a schedule, and it exists
// only to be timed and torn down. Needs an agent to point at, so this creates
// (and cleans up) a throwaway one.
import { check, group } from "k6";
import { BASE_URL, WORKSPACE } from "../config.js";
import { get, postJson, del } from "../http.js";
import { assertWriteAllowed } from "./guard.js";
import { resourceName } from "./naming.js";
import { tag } from "./tags.js";

const ws = (suffix) => `${BASE_URL}/v1/workspaces/${encodeURIComponent(WORKSPACE)}${suffix}`;

export const triggerLifecycle = {
  name: "trigger_lifecycle",
  run: () => {
    assertWriteAllowed("trigger_lifecycle");
    group("journey: trigger_lifecycle", () => {
      const agentName = resourceName("trigger-agent");
      const agentRes = postJson(
        ws("/agents/"),
        { name: agentName, tools: [] },
        "create_agent",
        tag("trigger_lifecycle", "create_agent")
      );
      if (agentRes.status >= 300) return;
      const agent = agentRes.json();

      const triggerName = resourceName("trigger");
      const createRes = postJson(
        ws("/triggers/"),
        {
          agent_id: agent.id,
          name: triggerName,
          trigger_type: "cron",
          cron_expression: "0 0 1 1 *", // once a year — irrelevant, enabled is false anyway
          enabled: false,
          task_parameters: { text: "reply with OK" },
        },
        "create",
        tag("trigger_lifecycle", "create")
      );
      check(createRes, { "trigger create -> 201": (r) => r.status === 201 });
      if (createRes.status < 300) {
        const trigger = createRes.json();
        check(trigger, { "trigger created disabled": (t) => t.is_active === false });

        const readRes = get(
          ws(`/triggers/${trigger.id}`),
          "read",
          tag("trigger_lifecycle", "read")
        );
        check(readRes, { "trigger read -> 200": (r) => r.status === 200 });

        const deleteRes = del(
          ws(`/triggers/${trigger.id}`),
          "delete",
          tag("trigger_lifecycle", "delete")
        );
        check(deleteRes, { "trigger delete -> 204/200": (r) => [200, 204].includes(r.status) });
      }

      del(ws(`/agents/${agent.id}`), "delete_agent", tag("trigger_lifecycle", "delete_agent"));
    });
  },
};
