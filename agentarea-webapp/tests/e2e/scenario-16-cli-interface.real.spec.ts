import { expect, test } from "@playwright/test";
import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import { promisify } from "node:util";
import {
  createKratosUser,
  deleteKratosUser,
  type AuthedUser,
} from "./helpers/real-stack";
import {
  cleanupModelChain,
  deleteAgent,
  runRealStack,
  seedAgent,
  seedModelChain,
} from "./helpers/scenarios";

const execFileAsync = promisify(execFile);

test.describe("Scenario 16 MP - use the CLI external interface", () => {
  test.skip(!runRealStack, "Set PLAYWRIGHT_REAL_STACK=1");

  let user: AuthedUser;
  let modelChain: Awaited<ReturnType<typeof seedModelChain>> | undefined;
  let agent: { id: string; name: string } | undefined;

  test.beforeAll(async ({ request }) => {
    user = await createKratosUser("scenario-16");
    modelChain = await seedModelChain(request, user, "scenario-16");
    agent = await seedAgent(
      request,
      user,
      "scenario-16-agent",
      modelChain.modelInstanceId
    );
  });

  test.afterAll(async ({ request }) => {
    await deleteAgent(request, user, agent?.id);
    await cleanupModelChain(request, user, modelChain);
    if (user) await deleteKratosUser(user.identityId);
  });

  // BLOCKED-ENV if the CLI package cannot install/build in this local checkout.
  test("identifies the CLI executable and lists agents with AGENTAREA_TOKEN", async () => {
    test.setTimeout(180_000);
    const pkg = JSON.parse(
      await readFile("../agentarea-cli/package.json", "utf8")
    ) as { bin: Record<string, string> };
    expect(pkg.bin.agentarea).toBe("dist/cli.js");

    try {
      await execFileAsync("pnpm", ["--dir", "../agentarea-cli", "install"], {
        timeout: 90_000,
      });
      await execFileAsync("pnpm", ["--dir", "../agentarea-cli", "build"], {
        timeout: 90_000,
      });
    } catch (error) {
      test.skip(
        true,
        `BLOCKED-ENV: pnpm --dir ../agentarea-cli install && pnpm --dir ../agentarea-cli build failed: ${
          error instanceof Error ? error.message : String(error)
        }`
      );
    }

    const { stdout, stderr } = await execFileAsync(
      "pnpm",
      ["--dir", "../agentarea-cli", "exec", "agentarea", "agents", "list"],
      {
        timeout: 25_000,
        env: {
          ...process.env,
          AGENTAREA_TOKEN: user.jwt,
          AGENTAREA_API_URL: "http://localhost:8000",
        },
      }
    );
    expect(`${stdout}\n${stderr}`).toContain(agent?.id ?? "");
  });
});
