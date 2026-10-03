import {
  expect,
  type APIRequestContext,
  type APIResponse,
  type Locator,
  type Page,
} from "@playwright/test";
import {
  appHref,
  appPath,
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
    const response = await page.goto(`${baseURL}${appHref(page, route)}`, {
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

// gotoCommitted returns before React hydrates under `next dev`; a fill or click
// that lands earlier is dropped or overwritten. React tags each hydrated DOM
// node with a `__reactProps$<id>` key, so its presence means the node is live.
export async function expectHydrated(target: Locator, timeout = 30_000) {
  await expect
    .poll(
      () =>
        target.evaluate((el) =>
          Object.keys(el).some((key) => key.startsWith("__reactProps$"))
        ),
      { timeout }
    )
    .toBe(true);
}

export async function expectPath(page: Page, path: string, timeout = 25_000) {
  await expect
    .poll(() => appPath(page), { timeout })
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
        if (appPath(page) !== path) return "redirected";
        const errors = await page
          .locator(
            ".form-error, .text-destructive, [role=alert], [data-nextjs-error-boundary], body"
          )
          .allInnerTexts()
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

async function expectOk(response: APIResponse, label: string) {
  if (!response.ok()) {
    throw new Error(
      `${label} failed: ${response.status()} ${JSON.stringify(await responseBody(response))}`
    );
  }
}

// Local Ollama gives seeded agents a REAL, executable model (zero cost /
// rate-limit). The worker rewrites localhost -> host.docker.internal, so
// endpoint_url "http://localhost:11434" reaches host Ollama. Only a run needs
// `ollama serve` with the model pulled; seeding the chain does not.
const OLLAMA_PROVIDER_KEY = "ollama";
const OLLAMA_MODEL = "qwen3:0.6b";

export const runLiveModel = process.env.PLAYWRIGHT_LIVE_MODEL === "1";
export const liveModelSkipReason = `Set PLAYWRIGHT_LIVE_MODEL=1 with \`ollama serve\` running and ${OLLAMA_MODEL} pulled: this needs a model that actually answers`;

type ModelChain = {
  providerSpecId: string;
  providerConfigId: string;
  modelSpecId: string;
  modelInstanceId: string;
  modelInstanceName: string;
};

// A workspace holds one spec per provider + model name, so each user gets one
// chain, shared by every agent seeded for them.
const userModelChains = new Map<string, Promise<ModelChain>>();

export function seedModelChain(
  request: APIRequestContext,
  user: AuthedUser,
  prefix: string
) {
  let chain = userModelChains.get(user.identityId);
  if (!chain) {
    chain = createModelChain(request, user, prefix);
    userModelChains.set(user.identityId, chain);
  }
  return chain;
}

async function createModelChain(
  request: APIRequestContext,
  user: AuthedUser,
  prefix: string
): Promise<ModelChain> {
  const provider = await authedRequest(
    request,
    user,
    "get",
    `/v1/provider-specs/by-key/${OLLAMA_PROVIDER_KEY}`
  );
  await expectOk(provider, `GET /v1/provider-specs/by-key/${OLLAMA_PROVIDER_KEY}`);
  const providerSpecId = (await provider.json()).id as string;

  const modelSpec = await authedRequest(request, user, "post", "/v1/model-specs/", {
    data: {
      provider_spec_id: providerSpecId,
      model_name: OLLAMA_MODEL,
      display_name: OLLAMA_MODEL,
      context_window: 40960,
      input_cost_per_token: "0",
      output_cost_per_token: "0",
    },
  });
  await expectOk(modelSpec, "POST /v1/model-specs/");
  const modelSpecBody = await modelSpec.json();

  const providerConfig = await authedRequest(
    request,
    user,
    "post",
    "/v1/provider-configs/",
    {
      data: {
        provider_spec_id: providerSpecId,
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
        description: `Playwright scenario model instance (local Ollama ${OLLAMA_MODEL})`,
      },
    }
  );
  await expectOk(modelInstance, "POST /v1/model-instances/");
  const modelInstanceBody = await modelInstance.json();

  return {
    providerSpecId,
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
  modelId?: string
) {
  const name = uniqueLabel(prefix);
  const response = await authedRequest(request, user, "post", "/v1/agents/", {
    data: {
      name,
      description: "Playwright scenario prerequisite agent",
      instruction: "Keep responses concise for deterministic tests.",
      model_id:
        modelId ?? (await seedModelChain(request, user, prefix)).modelInstanceId,
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
