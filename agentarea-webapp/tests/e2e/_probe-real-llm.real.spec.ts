import { expect, test } from "@playwright/test";
import {
  authedRequest,
  createKratosUser,
  deleteKratosUser,
  responseBody,
  uniqueLabel,
  type AuthedUser,
} from "./helpers/real-stack";

/**
 * TEMPORARY PROBE: does the core loop (provider -> model -> agent -> task ->
 * worker -> LLM -> result) actually work end to end with a REAL model?
 * Requires OPENROUTER_API_KEY in the env. Builtin catalog ids are global.
 */
// Local Ollama: zero cost, zero rate-limit, reproducible. Worker (in Docker)
// rewrites localhost -> host.docker.internal, so it reaches host Ollama.
const OLLAMA_SPEC = "55cd391c-c58b-43fd-ae4b-99d4a00ea00c";
const QWEN3_06B_SPEC = "368ea505-76c6-426e-ad6e-23458efbfc1d";

test.describe("PROBE real LLM end-to-end", () => {
  test.skip(
    process.env.PLAYWRIGHT_REAL_STACK !== "1" || !process.env.OPENROUTER_API_KEY,
    "needs PLAYWRIGHT_REAL_STACK=1 and OPENROUTER_API_KEY"
  );

  let user: AuthedUser;
  test.beforeAll(async () => {
    user = await createKratosUser("probe-llm");
  });
  test.afterAll(async () => {
    if (user) await deleteKratosUser(user.identityId);
  });

  test("runs a real task and gets a real result", async ({ request }) => {
    test.setTimeout(120_000);

    const specId = QWEN3_06B_SPEC;

    const cfg = await authedRequest(request, user, "post", "/v1/provider-configs/", {
      data: {
        provider_spec_id: OLLAMA_SPEC,
        name: uniqueLabel("probe-ollama"),
        endpoint_url: "http://localhost:11434",
      },
    });
    expect(cfg.ok(), `provider-config: ${cfg.status()} ${JSON.stringify(await responseBody(cfg))}`).toBeTruthy();
    const cfgId = (await cfg.json()).id;

    const inst = await authedRequest(request, user, "post", "/v1/model-instances/", {
      data: {
        provider_config_id: cfgId,
        model_spec_id: specId,
        name: uniqueLabel("probe-instance"),
      },
    });
    expect(inst.ok(), `model-instance: ${inst.status()} ${JSON.stringify(await responseBody(inst))}`).toBeTruthy();
    const instId = (await inst.json()).id;

    const agent = await authedRequest(request, user, "post", "/v1/agents/", {
      data: {
        name: uniqueLabel("probe-agent"),
        description: "probe",
        instruction: "You are a terse assistant. Answer in one short word.",
        model_id: instId,
        tools: [],
        planning: false,
        agent_type: "stateless",
      },
    });
    expect(agent.ok(), `agent: ${agent.status()} ${JSON.stringify(await responseBody(agent))}`).toBeTruthy();
    const agentId = (await agent.json()).id;

    // POST returns a live SSE stream of the run; APIRequestContext buffers it,
    // so .text() resolves once the stream closes (task finished).
    const submit = await authedRequest(request, user, "post", `/v1/agents/${agentId}/tasks/`, {
      data: { description: "Reply with exactly the word: PONG" },
      headers: { accept: "text/event-stream" },
    });
    expect(submit.ok(), `submit HTTP: ${submit.status()}`).toBeTruthy();
    const sse = await submit.text();
    console.log("PROBE SSE (last 600):", sse.slice(-600));

    const taskId =
      sse.match(/"task_id"\s*:\s*"([0-9a-f-]{36})"/i)?.[1] ??
      sse.match(/"id"\s*:\s*"([0-9a-f-]{36})"/i)?.[1];
    console.log("PROBE taskId:", taskId);

    // Confirm final state via the durable record (not stream-only).
    let last: any = null;
    const deadline = Date.now() + 90_000;
    while (taskId && Date.now() < deadline) {
      const got = await authedRequest(request, user, "get", `/v1/agents/${agentId}/tasks/${taskId}`);
      last = await got.json();
      console.log(`PROBE status=${last.status} cost=${last.total_cost ?? "?"}`);
      if (["completed", "failed", "cancelled", "error"].includes(String(last.status))) break;
      await new Promise((r) => setTimeout(r, 2500));
    }
    console.log("PROBE final result:", JSON.stringify(last?.result)?.slice(0, 400));
    expect(last?.status, `final task: ${JSON.stringify(last)?.slice(0, 600)}`).toBe("completed");
    expect(JSON.stringify(last?.result ?? "").length, "task produced some result").toBeGreaterThan(2);
  });
});
