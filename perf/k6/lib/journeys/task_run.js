// Starts a real task on a throwaway agent with the cheapest available model
// and a trivial prompt, then measures three checkpoints:
//
//   task_accepted     duration of POST .../tasks/sync once the response body
//                     confirms status "running" (or "scheduled") — a 2xx
//                     alone isn't enough: temporal_task_manager.py can still
//                     return HTTP 200 with status "failed" if the workflow
//                     failed to start (e.g. AgentModelNotConfiguredError path).
//   task_first_event  time from acceptance until GET .../events returns the
//                     first persisted event.
//   task_completed    time from acceptance until GET .../status reports a
//                     terminal status.
//
// Both are polled, not read off the SSE stream: a web conversation's stream
// stays open across completed turns while the workflow waits for a follow-up
// (follow_execution in task_stream.py), so it does not end at task.completed
// and k6 cannot see frames mid-stream.
//
// This is the one journey with a real per-run LLM cost, so it is never part
// of the random weighted pick — the caller (a dedicated shared-iterations
// scenario, see scenarios/journeys/*.js) is what caps it at N runs total,
// independent of VU count.
import { check, group, sleep } from "k6";
import { BASE_URL, WORKSPACE } from "../config.js";
import { get, postJson, del } from "../http.js";
import { assertWriteAllowed } from "./guard.js";
import { resourceName } from "./naming.js";
import { taskAccepted, taskFirstEvent, taskCompleted, taskRuns } from "./metrics.js";
import { tag } from "./tags.js";

const ws = (suffix) => `${BASE_URL}/v1/workspaces/${encodeURIComponent(WORKSPACE)}${suffix}`;

// Confirmed live on RU prod (2026-09-27, read-only against jamakase54): a
// platform-managed ProviderConfig ("AgentArea"/"agentarea") makes model
// instance kimi-k2.6 visible to every workspace with no provider key of its
// own required (ModelInstanceRepository._get_workspace_filter widens reads
// to the platform's rows). That id may not carry over to perf-k6 verbatim —
// override with MODEL_INSTANCE_ID once perf-k6 exists and re-verify.
const DEFAULT_MODEL_INSTANCE_ID = "0b6915c2-e373-5c1c-a415-0dbcb16afeb2";

function resolveModelInstanceId() {
  if (__ENV.MODEL_INSTANCE_ID) return __ENV.MODEL_INSTANCE_ID;
  const res = get(ws("/model-instances/"), "resolve_model", tag("task_run", "resolve_model"));
  if (res.status === 200) {
    const instances = res.json() || [];
    const platformOne = instances.find((i) => i.provider_key === "agentarea");
    if (platformOne) return platformOne.id;
    if (instances.length) return instances[0].id;
  }
  return DEFAULT_MODEL_INSTANCE_ID;
}

const COMPLETION_TIMEOUT_S = Number(__ENV.TASK_COMPLETION_TIMEOUT_S || 90);
const POLL_INTERVAL_S = 0.25;
const TERMINAL = ["completed", "failed", "cancelled"];

export const taskRunJourney = {
  name: "task_run",
  run: () => {
    assertWriteAllowed("task_run");
    group("journey: task_run", () => {
      const modelInstanceId = resolveModelInstanceId();
      const agentName = resourceName("task-agent");
      const agentRes = postJson(
        ws("/agents/"),
        { name: agentName, tools: [], model_id: modelInstanceId },
        "create_agent",
        tag("task_run", "create_agent")
      );
      check(agentRes, { "task_run agent create -> 200/201": (r) => r.status === 200 || r.status === 201 });
      if (agentRes.status >= 300) return;
      const agent = agentRes.json();

      const createTaskRes = postJson(
        ws(`/agents/${agent.id}/tasks/sync`),
        { description: "Reply with exactly: OK" },
        "accept",
        tag("task_run", "accept")
      );
      const accepted = check(createTaskRes, {
        // A 2xx alone isn't acceptance — the body can still say "failed" if
        // the workflow never actually started (e.g. no usable model).
        "task accept -> 2xx and status running/scheduled": (r) =>
          (r.status === 200 || r.status === 201) &&
          ["running", "scheduled"].includes(r.json("status")),
      });
      if (accepted) {
        taskAccepted.add(createTaskRes.timings.duration, { journey: "task_run" });
        taskRuns.add(1, { journey: "task_run" });
        const task = createTaskRes.json();

        const taskPath = `/agents/${agent.id}/tasks/${task.id}`;
        const acceptedAt = Date.now();
        let firstEventAt = null;
        let finalStatus = null;
        while ((Date.now() - acceptedAt) / 1000 < COMPLETION_TIMEOUT_S) {
          if (firstEventAt === null) {
            const eventsRes = get(ws(`${taskPath}/events`), "events", tag("task_run", "events"));
            if (eventsRes.status === 200 && (eventsRes.json("events") || []).length > 0) {
              firstEventAt = Date.now();
              taskFirstEvent.add(firstEventAt - acceptedAt, { journey: "task_run" });
            }
          }
          const statusRes = get(ws(`${taskPath}/status`), "status", tag("task_run", "status"));
          if (statusRes.status === 200 && TERMINAL.includes(statusRes.json("status"))) {
            finalStatus = statusRes.json("status");
            break;
          }
          sleep(POLL_INTERVAL_S);
        }
        if (finalStatus !== null) {
          taskCompleted.add(Date.now() - acceptedAt, { journey: "task_run" });
        }
        check(finalStatus, {
          "task reached a terminal state": (status) => status !== null,
          "task completed": (status) => status === "completed",
        });
      }

      del(ws(`/agents/${agent.id}`), "delete_agent", tag("task_run", "delete_agent"));
    });
  },
};
