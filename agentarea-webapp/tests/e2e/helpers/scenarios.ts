import { expect, type APIRequestContext, type Page } from "@playwright/test";
import {
  authedRequest,
  responseBody,
  uniqueLabel,
  type AuthedUser,
} from "./real-stack";

export const runRealStack = process.env.PLAYWRIGHT_REAL_STACK === "1";

export const baseURL =
  process.env.PLAYWRIGHT_BASE_URL ??
  `http://localhost:${process.env.PLAYWRIGHT_WEB_PORT ?? "3100"}`;

export async function gotoCommitted(page: Page, route: string) {
  try {
    const response = await page.goto(`${baseURL}${route}`, {
      waitUntil: "commit",
      timeout: 60_000,
    });
    expect(page.url(), `${route} should not redirect to login`).not.toMatch(
      /\/auth\/login/
    );
    if (response) {
      expect(response.status(), `${route} HTTP status`).toBeLessThan(400);
    }
    await page
      .waitForLoadState("domcontentloaded", { timeout: 8_000 })
      .catch(() => undefined);
    await expect(
      page.getByText("Something went wrong", { exact: false }),
      `${route} should not show the error boundary`
    ).toHaveCount(0);
    return response;
  } catch (error) {
    if (String(error).includes("Timeout")) {
      throw new Error(
        `${route} did not return its first byte within 60s - slow or hanging server-side render`
      );
    }
    throw error;
  }
}

export async function expectPath(page: Page, path: string, timeout = 25_000) {
  await expect
    .poll(() => new URL(page.url()).pathname, { timeout })
    .toBe(path);
}

export async function expectRedirectedAwayFrom(
  page: Page,
  path: string,
  timeout = 30_000
) {
  await expect
    .poll(
      async () => {
        const current = new URL(page.url()).pathname;
        if (current !== path) return "redirected";
        const errors = await page
          .locator(
            ".form-error, .text-destructive, [role=alert], [data-nextjs-error-boundary], body"
          )
          .allTextContents()
          .catch(() => [] as string[]);
        const joined = errors
          .map((text) => text.trim())
          .filter((text) =>
            /error|failed|invalid|required|not valid|objects are not valid|something went wrong|422/i.test(
              text
            )
          )
          .join(" | ");
        return joined ? `error: ${joined}` : "pending";
      },
      { timeout }
    )
    .toBe("redirected");
}

async function expectOk(response: any, label: string) {
  if (!response.ok()) {
    throw new Error(
      `${label} failed: ${response.status()} ${JSON.stringify(await responseBody(response))}`
    );
  }
}

// Builtin catalog ids (global). Local Ollama gives seeded agents a REAL,
// executable model (zero cost / rate-limit). The worker rewrites localhost ->
// host.docker.internal, so endpoint_url "http://localhost:11434" reaches host
// Ollama. Requires `ollama serve` + the qwen3:0.6b model pulled.
const OLLAMA_PROVIDER_SPEC = "55cd391c-c58b-43fd-ae4b-99d4a00ea00c";
const OLLAMA_QWEN3_MODEL_SPEC = "368ea505-76c6-426e-ad6e-23458efbfc1d"; // qwen3:0.6b

export async function seedModelChain(
  request: APIRequestContext,
  user: AuthedUser,
  prefix: string
) {
  const provider = { id: OLLAMA_PROVIDER_SPEC };
  const modelSpecBody = { id: OLLAMA_QWEN3_MODEL_SPEC };

  const providerConfig = await authedRequest(
    request,
    user,
    "post",
    "/v1/provider-configs/",
    {
      data: {
        provider_spec_id: provider.id,
        name: uniqueLabel(`${prefix}-provider`),
        endpoint_url: "http://localhost:11434",
      },
    }
  );
  await expectOk(providerConfig, "POST /v1/provider-configs/");
  const providerConfigBody = await providerConfig.json();

  const modelInstance = await authedRequest(
    request,
    user,
    "post",
    "/v1/model-instances/",
    {
      data: {
        provider_config_id: providerConfigBody.id,
        model_spec_id: modelSpecBody.id,
        name: uniqueLabel(`${prefix}-instance`),
        description: "Playwright scenario model instance (local Ollama qwen3:0.6b)",
      },
    }
  );
  await expectOk(modelInstance, "POST /v1/model-instances/");
  const modelInstanceBody = await modelInstance.json();

  return {
    providerSpecId: provider.id as string,
    providerConfigId: providerConfigBody.id as string,
    modelSpecId: modelSpecBody.id as string,
    modelInstanceId: modelInstanceBody.id as string,
    modelInstanceName: modelInstanceBody.name as string,
  };
}

export async function cleanupModelChain(
  request: APIRequestContext,
  user: AuthedUser,
  ids?: {
    providerConfigId?: string;
    modelSpecId?: string;
    modelInstanceId?: string;
  }
) {
  if (!ids) return;
  if (ids.modelInstanceId) {
    await authedRequest(
      request,
      user,
      "delete",
      `/v1/model-instances/${ids.modelInstanceId}`
    ).catch(() => undefined);
  }
  if (ids.providerConfigId) {
    await authedRequest(
      request,
      user,
      "delete",
      `/v1/provider-configs/${ids.providerConfigId}`
    ).catch(() => undefined);
  }
  if (ids.modelSpecId) {
    await authedRequest(
      request,
      user,
      "delete",
      `/v1/model-specs/${ids.modelSpecId}`
    ).catch(() => undefined);
  }
}

export async function seedAgent(
  request: APIRequestContext,
  user: AuthedUser,
  prefix = "scenario-agent",
  modelId = "gpt-4o-mini"
) {
  const name = uniqueLabel(prefix);
  const response = await authedRequest(request, user, "post", "/v1/agents/", {
    data: {
      name,
      description: "Playwright scenario prerequisite agent",
      instruction: "Keep responses concise for deterministic tests.",
      model_id: modelId,
      tools: [],
      planning: false,
      agent_type: "stateless",
    },
  });
  await expectOk(response, "POST /v1/agents/");
  return (await response.json()) as { id: string; name: string };
}

export async function deleteAgent(
  request: APIRequestContext,
  user: AuthedUser,
  agentId?: string
) {
  if (!agentId) return;
  await authedRequest(request, user, "delete", `/v1/agents/${agentId}`).catch(
    () => undefined
  );
}

export async function seedSkill(
  request: APIRequestContext,
  user: AuthedUser,
  prefix = "scenario-skill"
) {
  const name = uniqueLabel(prefix);
  const response = await authedRequest(request, user, "post", "/v1/skills", {
    data: {
      name,
      content: `---\nname: ${name}\ndescription: Scenario prerequisite skill\n---\n\n# ${name}\n`,
    },
  });
  await expectOk(response, "POST /v1/skills");
  return (await response.json()) as { id: string; name: string };
}

export async function seedMcpServer(
  request: APIRequestContext,
  user: AuthedUser,
  prefix = "scenario-mcp"
) {
  const name = uniqueLabel(prefix);
  const response = await authedRequest(request, user, "post", "/v1/mcp-servers/", {
    data: {
      name,
      description: "Playwright scenario prerequisite MCP server",
      cmd: ["node", "--version"],
      tags: ["playwright"],
    },
  });
  await expectOk(response, "POST /v1/mcp-servers/");
  return (await response.json()) as { id: string; name: string };
}

export async function deleteMcpServer(
  request: APIRequestContext,
  user: AuthedUser,
  serverId?: string
) {
  if (!serverId) return;
  await authedRequest(request, user, "delete", `/v1/mcp-servers/${serverId}`).catch(
    () => undefined
  );
}

export async function deleteSkill(
  request: APIRequestContext,
  user: AuthedUser,
  skillId?: string
) {
  if (!skillId) return;
  await authedRequest(request, user, "delete", `/v1/skills/${skillId}`).catch(
    () => undefined
  );
}

export async function deletePolicy(
  request: APIRequestContext,
  user: AuthedUser,
  policyId?: string
) {
  if (!policyId) return;
  await authedRequest(request, user, "delete", `/v1/policies/${policyId}`).catch(
    () => undefined
  );
}

export async function deleteTrigger(
  request: APIRequestContext,
  user: AuthedUser,
  triggerId?: string
) {
  if (!triggerId) return;
  await authedRequest(request, user, "delete", `/v1/triggers/${triggerId}`).catch(
    () => undefined
  );
}

export async function selectFirstRadixOption(page: Page, triggerName?: string) {
  if (triggerName) {
    await page.getByRole("combobox", { name: triggerName }).click();
  } else {
    await page.getByRole("combobox").first().click();
  }
  await page.getByRole("option").first().click();
}
