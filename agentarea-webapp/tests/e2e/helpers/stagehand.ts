import { Stagehand, AISdkClient } from "@browserbasehq/stagehand";
import type { Page } from "@browserbasehq/stagehand";
import { createOpenRouter } from "@openrouter/ai-sdk-provider";
import {
  createKratosUser,
  deleteKratosUser,
  type AuthedUser,
} from "./real-stack";

/**
 * AI-driven E2E harness built on top of the existing real-stack Playwright
 * helpers. Authentication stays deterministic (a real Kratos session injected
 * as a cookie); only the "soft" in-page user journey is delegated to the LLM
 * via Stagehand's act()/extract()/observe() primitives.
 *
 * Stagehand v3 note: act/extract/observe are methods on the Stagehand instance
 * itself (they operate on the active page), while navigation and cookies go
 * through `stagehand.context` (a CDP-backed context, not a Playwright one).
 *
 * The driver model is fully env-configurable so we never hardcode a provider:
 *   OPENROUTER_API_KEY   required - key for the OpenRouter gateway
 *   STAGEHAND_MODEL      OpenRouter model slug (default: z-ai/glm-4.7)
 *   STAGEHAND_VERBOSE    0|1|2 Stagehand log verbosity (default: 1)
 *   HEADED               set to run the local browser headed
 */

export const baseURL =
  process.env.PLAYWRIGHT_BASE_URL ??
  `http://localhost:${process.env.PLAYWRIGHT_WEB_PORT ?? "3100"}`;

export const stagehandModel = process.env.STAGEHAND_MODEL ?? "z-ai/glm-4.7";

export const aiSpecsEnabled =
  process.env.PLAYWRIGHT_REAL_STACK === "1" &&
  Boolean(process.env.OPENROUTER_API_KEY);

export const aiSkipReason =
  "Set PLAYWRIGHT_REAL_STACK=1 and OPENROUTER_API_KEY to run Stagehand AI specs";

function makeLlmClient() {
  const apiKey = process.env.OPENROUTER_API_KEY;
  if (!apiKey) {
    throw new Error("OPENROUTER_API_KEY is required for Stagehand AI specs");
  }
  const openrouter = createOpenRouter({ apiKey });
  return new AISdkClient({ model: openrouter(stagehandModel) });
}

export async function createStagehand() {
  const stagehand = new Stagehand({
    env: "LOCAL",
    llmClient: makeLlmClient(),
    verbose: Number(process.env.STAGEHAND_VERBOSE ?? "1") as 0 | 1 | 2,
    localBrowserLaunchOptions: { headless: !process.env.HEADED },
  });
  await stagehand.init();
  return stagehand;
}

export type AuthedStagehandContext = {
  stagehand: Stagehand;
  page: Page;
  user: AuthedUser;
};

/**
 * Creates a fresh Kratos user, boots a Stagehand-controlled local browser with
 * the user's session injected, lands on the app shell, runs `fn`, then always
 * tears down the browser and deletes the Kratos identity.
 */
export async function withAuthedStagehand(
  prefix: string,
  fn: (ctx: AuthedStagehandContext) => Promise<void>
) {
  const user = await createKratosUser(prefix);
  const stagehand = await createStagehand();
  try {
    await stagehand.context.addCookies([
      {
        name: user.sessionCookie.name,
        value: user.sessionCookie.value,
        domain: "localhost",
        path: "/",
        httpOnly: true,
        sameSite: "Lax",
        expires: Math.floor(Date.now() / 1000) + 24 * 60 * 60,
      },
    ]);

    const page =
      stagehand.context.pages()[0] ?? (await stagehand.context.newPage());
    await page.goto(`${baseURL}/`);

    await fn({ stagehand, page, user });
  } finally {
    await stagehand.close().catch(() => undefined);
    await deleteKratosUser(user.identityId);
  }
}
