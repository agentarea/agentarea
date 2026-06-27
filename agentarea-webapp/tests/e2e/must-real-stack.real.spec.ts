import { expect, test } from "@playwright/test";
import {
  apiBaseURL,
  authedFetch,
  authedRequest,
  createKratosUser,
  deleteKratosUser,
  responseBody,
  uniqueLabel,
} from "./helpers/real-stack";
import { requirementTitle } from "./requirements";

const runRealStack = process.env.PLAYWRIGHT_REAL_STACK === "1";

const openApiSpec = {
  openapi: "3.0.3",
  info: { title: "Playwright Pets API", version: "1.0.0" },
  servers: [{ url: "https://example.test" }],
  paths: {
    "/pets": {
      get: {
        operationId: "listPets",
        summary: "List pets",
        responses: { "200": { description: "ok" } },
      },
    },
  },
};

async function expectOk(response: any) {
  if (!response.ok()) {
    throw new Error(`${response.status()} ${JSON.stringify(await responseBody(response))}`);
  }
}

async function createAgent(request: any, user: any, prefix = "pw-agent") {
  const name = uniqueLabel(prefix);
  const response = await authedRequest(request, user, "post", "/v1/agents/", {
    data: {
      name,
      description: "Playwright real-stack agent",
      instruction: "Keep responses concise.",
      model_id: "gpt-4o-mini",
      tools: [],
      planning: false,
      agent_type: "stateless",
    },
  });
  await expectOk(response);
  return response.json();
}

async function deleteAgent(request: any, user: any, agentId?: string) {
  if (agentId) {
    await authedRequest(request, user, "delete", `/v1/agents/${agentId}`).catch(() => undefined);
  }
}

test.describe("must functional requirements real stack", () => {
  test.skip(!runRealStack, "Set PLAYWRIGHT_REAL_STACK=1 to run against a live stand");

  test(
    requirementTitle("FR-03", "agent create/detail/edit/list/delete works through the real API"),
    async ({ request }) => {
      const user = await createKratosUser("pw-fr03");
      let agentId: string | undefined;
      try {
        const created = await createAgent(request, user, "pw-fr03-agent");
        agentId = created.id;
        expect(created.name).toMatch(/^pw-fr03-agent-/);
        expect(created.model_id).toBe("gpt-4o-mini");

        const detail = await authedRequest(request, user, "get", `/v1/agents/${agentId}`);
        await expectOk(detail);
        expect((await detail.json()).id).toBe(agentId);

        const renamed = `${created.name}-edited`;
        const patched = await authedRequest(request, user, "patch", `/v1/agents/${agentId}`, {
          data: { name: renamed, description: "Edited by Playwright" },
        });
        await expectOk(patched);
        const patchedPayload = await patched.json();
        expect(patchedPayload.name).toBe(renamed);
        expect(patchedPayload.description).toBe("Edited by Playwright");

        const list = await authedRequest(request, user, "get", "/v1/agents/");
        await expectOk(list);
        expect((await list.json()).some((item: any) => item.id === agentId)).toBe(true);

        const deleted = await authedRequest(request, user, "delete", `/v1/agents/${agentId}`);
        await expectOk(deleted);
        agentId = undefined;

        const afterDelete = await authedRequest(request, user, "get", `/v1/agents/${created.id}`);
        expect(afterDelete.status()).toBe(404);
      } finally {
        await deleteAgent(request, user, agentId);
        await deleteKratosUser(user.identityId);
      }
    }
  );

  test(
    requirementTitle(
      "FR-04",
      "provider config, model instance, and model test failure state are real"
    ),
    async ({ request }) => {
      const user = await createKratosUser("pw-fr04");
      let providerConfigId: string | undefined;
      let modelInstanceId: string | undefined;
      let createdModelSpecId: string | undefined;
      try {
        const specs = await authedRequest(request, user, "get", "/v1/provider-specs/");
        await expectOk(specs);
        const provider = (await specs.json())[0];
        expect(provider?.id).toEqual(expect.any(String));

        const createdSpec = await authedRequest(request, user, "post", "/v1/model-specs/", {
          data: {
            provider_spec_id: provider.id,
            model_name: uniqueLabel("pw-fr04-model"),
            display_name: "Playwright Model",
            context_window: 4096,
          },
        });
        await expectOk(createdSpec);
        const modelSpec = await createdSpec.json();
        createdModelSpecId = modelSpec.id;

        const providerConfig = await authedRequest(request, user, "post", "/v1/provider-configs/", {
          data: {
            provider_spec_id: provider.id,
            name: uniqueLabel("pw-fr04-provider"),
            api_key: "pw-secret-value-never-return",
            endpoint_url: "https://example.invalid",
          },
        });
        await expectOk(providerConfig);
        const providerPayload = await providerConfig.json();
        providerConfigId = providerPayload.id;
        expect(JSON.stringify(providerPayload)).not.toContain("pw-secret-value-never-return");

        const modelInstance = await authedRequest(request, user, "post", "/v1/model-instances/", {
          data: {
            provider_config_id: providerConfigId,
            model_spec_id: modelSpec.id,
            name: uniqueLabel("pw-fr04-instance"),
            description: "Playwright model instance",
          },
        });
        await expectOk(modelInstance);
        const instancePayload = await modelInstance.json();
        modelInstanceId = instancePayload.id;
        expect(instancePayload.provider_config_id).toBe(providerConfigId);
        expect(instancePayload.model_spec_id).toBe(modelSpec.id);

        const testResult = await authedRequest(request, user, "post", "/v1/model-instances/test", {
          data: {
            provider_config_id: providerConfigId,
            model_spec_id: modelSpec.id,
            test_message: "hello",
          },
          timeout: 20_000,
        });
        await expectOk(testResult);
        const testPayload = await testResult.json();
        expect(testPayload.success).toBe(false);
        expect(testPayload.message).toEqual(expect.any(String));

        const list = await authedRequest(request, user, "get", "/v1/model-instances/");
        await expectOk(list);
        expect((await list.json()).some((item: any) => item.id === modelInstanceId)).toBe(true);
      } finally {
        if (modelInstanceId) {
          await authedRequest(request, user, "delete", `/v1/model-instances/${modelInstanceId}`).catch(
            () => undefined
          );
        }
        if (providerConfigId) {
          await authedRequest(
            request,
            user,
            "delete",
            `/v1/provider-configs/${providerConfigId}`
          ).catch(() => undefined);
        }
        if (createdModelSpecId) {
          await authedRequest(request, user, "delete", `/v1/model-specs/${createdModelSpecId}`).catch(
            () => undefined
          );
        }
        await deleteKratosUser(user.identityId);
      }
    }
  );

  test(
    requirementTitle("FR-05", "task creation returns a task id and task lists expose it"),
    async ({ request }) => {
      const user = await createKratosUser("pw-fr05");
      let agentId: string | undefined;
      try {
        const agent = await createAgent(request, user, "pw-fr05-agent");
        agentId = agent.id;

        const task = await authedRequest(request, user, "post", `/v1/agents/${agentId}/tasks/sync`, {
          data: {
            description: "Playwright task smoke. It may fail later if no provider is configured.",
            parameters: { source: "playwright-real-stack" },
          },
          timeout: 20_000,
        });
        await expectOk(task);
        const taskPayload = await task.json();
        expect(taskPayload.id).toEqual(expect.any(String));
        expect(taskPayload.agent_id).toBe(agentId);
        expect(["pending", "running", "completed", "failed"]).toContain(taskPayload.status);

        const agentTasks = await authedRequest(request, user, "get", `/v1/agents/${agentId}/tasks/`);
        await expectOk(agentTasks);
        expect((await agentTasks.json()).some((item: any) => item.id === taskPayload.id)).toBe(true);

        const globalTasks = await authedRequest(request, user, "get", "/v1/tasks/");
        await expectOk(globalTasks);
        expect((await globalTasks.json()).some((item: any) => item.id === taskPayload.id)).toBe(true);
      } finally {
        await deleteAgent(request, user, agentId);
        await deleteKratosUser(user.identityId);
      }
    }
  );

  test(
    requirementTitle("FR-06", "task SSE stream emits connected/task-created events"),
    async ({ request }) => {
      const user = await createKratosUser("pw-fr06");
      let agentId: string | undefined;
      try {
        const agent = await createAgent(request, user, "pw-fr06-agent");
        agentId = agent.id;

        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 15_000);
        const response = await fetch(`${apiBaseURL}/v1/agents/${agentId}/tasks/`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${user.jwt}`,
            "content-type": "application/json",
          },
          body: JSON.stringify({
            description: "Playwright SSE smoke",
            parameters: { source: "playwright-real-stack" },
          }),
          signal: controller.signal,
        });
        expect(response.ok).toBeTruthy();
        const reader = response.body?.getReader();
        expect(reader).toBeTruthy();

        let text = "";
        while (!text.includes("event: task_created") && !text.includes("event: error")) {
          const chunk = await reader!.read();
          if (chunk.done) break;
          text += new TextDecoder().decode(chunk.value);
        }
        clearTimeout(timeout);
        controller.abort();

        expect(text).toContain("event: connected");
        expect(text).toMatch(/event: (task_created|error)/);
      } finally {
        await deleteAgent(request, user, agentId);
        await deleteKratosUser(user.identityId);
      }
    }
  );

  test(
    requirementTitle("FR-07", "MCP server spec and command instance can be created and verified"),
    async ({ request }) => {
      const user = await createKratosUser("pw-fr07");
      let serverId: string | undefined;
      let instanceId: string | undefined;
      try {
        const invalid = await authedRequest(request, user, "post", "/v1/mcp-server-instances/validate", {
          data: { type: "url" },
        });
        await expectOk(invalid);
        expect((await invalid.json()).valid).toBe(false);

        const server = await authedRequest(request, user, "post", "/v1/mcp-servers/", {
          data: {
            name: uniqueLabel("pw-fr07-server"),
            description: "Playwright command MCP server",
            cmd: ["node", "--version"],
            tags: ["playwright"],
          },
        });
        await expectOk(server);
        serverId = (await server.json()).id;

        const instance = await authedRequest(request, user, "post", "/v1/mcp-server-instances/", {
          data: {
            name: uniqueLabel("pw-fr07-instance"),
            description: "Playwright command MCP instance",
            server_spec_id: serverId,
            json_spec: { type: "command", command: ["node", "--version"], environment: {} },
          },
          timeout: 20_000,
        });
        expect([201, 202]).toContain(instance.status());
        const instancePayload = await instance.json();
        instanceId = instancePayload.id;
        expect(instancePayload.verification).toBeDefined();

        let verification = instancePayload.verification;
        for (let attempt = 0; attempt < 10; attempt += 1) {
          if (verification?.status && verification.status !== "never_attempted") {
            break;
          }
          await new Promise((resolve) => setTimeout(resolve, 500));
          const detail = await authedRequest(
            request,
            user,
            "get",
            `/v1/mcp-server-instances/${instanceId}`
          );
          await expectOk(detail);
          verification = (await detail.json()).verification;
        }
        expect(["in_progress", "succeeded", "failed"]).toContain(verification?.status);
      } finally {
        if (instanceId) {
          await authedRequest(
            request,
            user,
            "delete",
            `/v1/mcp-server-instances/${instanceId}`
          ).catch(() => undefined);
        }
        if (serverId) {
          await authedRequest(request, user, "delete", `/v1/mcp-servers/${serverId}`).catch(
            () => undefined
          );
        }
        await deleteKratosUser(user.identityId);
      }
    }
  );

  test(
    requirementTitle("FR-08", "OpenAPI spec preview, validation, connection, and agent attachment work"),
    async ({ request }) => {
      const user = await createKratosUser("pw-fr08");
      let connectionId: string | undefined;
      let agentId: string | undefined;
      try {
        const preview = await authedRequest(request, user, "post", "/v1/openapi-connections/preview-spec", {
          data: { spec_content: openApiSpec },
        });
        await expectOk(preview);
        const previewPayload = await preview.json();
        expect(previewPayload.title).toBe("Playwright Pets API");
        expect(previewPayload.tools.some((tool: any) => tool.name === "listPets")).toBe(true);

        const invalid = await authedRequest(
          request,
          user,
          "post",
          "/v1/openapi-connections/preview-spec",
          { data: { spec_content: { openapi: "2.0.0", info: { title: "Bad" }, paths: {} } } }
        );
        expect(invalid.status()).toBe(400);

        const connection = await authedRequest(request, user, "post", "/v1/openapi-connections/", {
          data: {
            name: uniqueLabel("pw-fr08-openapi"),
            base_url: "https://example.com",
            description: "Playwright OpenAPI connection",
            spec_content: openApiSpec,
            custom_headers: [{ name: "Authorization", value: "Bearer secret-value" }],
          },
        });
        expect(connection.status()).toBe(201);
        const connectionPayload = await connection.json();
        connectionId = connectionPayload.id;
        expect(connectionPayload.available_tools.some((tool: any) => tool.name === "listPets")).toBe(
          true
        );
        expect(JSON.stringify(connectionPayload)).not.toContain("secret-value");

        const agent = await authedRequest(request, user, "post", "/v1/agents/", {
          data: {
            name: uniqueLabel("pw-fr08-agent"),
            description: "Agent with OpenAPI tool",
            instruction: "Use the attached OpenAPI tool when needed.",
            model_id: "gpt-4o-mini",
            tools: [{ type: "openapi", name: "listPets", settings: { connection_id: connectionId } }],
          },
        });
        await expectOk(agent);
        const agentPayload = await agent.json();
        agentId = agentPayload.id;
        expect(agentPayload.tools.some((tool: any) => tool.type === "openapi")).toBe(true);
      } finally {
        await deleteAgent(request, user, agentId);
        if (connectionId) {
          await authedRequest(
            request,
            user,
            "delete",
            `/v1/openapi-connections/${connectionId}`
          ).catch(() => undefined);
        }
        await deleteKratosUser(user.identityId);
      }
    }
  );

  test(
    requirementTitle("FR-09", "webhook trigger lifecycle and public execution are visible"),
    async ({ request }) => {
      const user = await createKratosUser("pw-fr09");
      let agentId: string | undefined;
      let triggerId: string | undefined;
      try {
        const agent = await createAgent(request, user, "pw-fr09-agent");
        agentId = agent.id;
        const webhookId = uniqueLabel("pw-fr09-webhook").replace(/[^a-zA-Z0-9_-]/g, "_");

        const trigger = await authedRequest(request, user, "post", "/v1/triggers/", {
          data: {
            name: uniqueLabel("pw-fr09-trigger"),
            description: "Playwright webhook trigger",
            agent_id: agentId,
            trigger_type: "webhook",
            task_parameters: { source: "playwright-real-stack" },
            webhook_id: webhookId,
            allowed_methods: ["POST"],
            webhook_type: "generic",
            enabled: true,
          },
        });
        expect(trigger.status()).toBe(201);
        const triggerPayload = await trigger.json();
        triggerId = triggerPayload.id;
        expect(triggerPayload.webhook_id).toBe(webhookId);
        expect(triggerPayload.is_active).toBe(true);

        const disabled = await authedRequest(request, user, "post", `/v1/triggers/${triggerId}/disable`);
        await expectOk(disabled);
        expect((await disabled.json()).is_active).toBe(false);

        const inactiveWebhook = await request.post(`${apiBaseURL}/webhooks/${webhookId}`, {
          data: { event: "inactive-check" },
        });
        expect(inactiveWebhook.status()).toBe(400);

        const enabled = await authedRequest(request, user, "post", `/v1/triggers/${triggerId}/enable`);
        await expectOk(enabled);
        expect((await enabled.json()).is_active).toBe(true);

        const webhook = await request.post(`${apiBaseURL}/webhooks/${webhookId}`, {
          data: { event: "playwright-event" },
          timeout: 20_000,
        });
        expect(webhook.status()).toBe(200);
        const webhookPayload = await responseBody(webhook);
        expect(JSON.stringify(webhookPayload)).toMatch(/status|message|task|error/i);

        const executions = await authedRequest(
          request,
          user,
          "get",
          `/v1/triggers/${triggerId}/executions`
        );
        await expectOk(executions);
        expect(await executions.json()).toHaveProperty("executions");
      } finally {
        if (triggerId) {
          await authedRequest(request, user, "delete", `/v1/triggers/${triggerId}`).catch(
            () => undefined
          );
        }
        await deleteAgent(request, user, agentId);
        await deleteKratosUser(user.identityId);
      }
    }
  );
});
