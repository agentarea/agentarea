import { createEnv } from "@t3-oss/env-nextjs";
import { z } from "zod";

export const env = createEnv({
  server: {
    AGENTAREA_AUTH_KRATOS_ADMIN_URL: z.string().url(),
    ORY_SDK_URL: z.string().url(),
    ORY_BROWSER_URL: z.string().url().optional(),
    AGENTAREA_API_URL: z.string().url(),
    AGENTAREA_MCP_APPS_ORIGIN: z.string().url(),
    AGENTAREA_APP_ORIGIN: z.string().url(),
  },
  client: {},
  runtimeEnv: {
    AGENTAREA_AUTH_KRATOS_ADMIN_URL: process.env.AGENTAREA_AUTH_KRATOS_ADMIN_URL,
    ORY_SDK_URL: process.env.ORY_SDK_URL,
    ORY_BROWSER_URL: process.env.ORY_BROWSER_URL,
    AGENTAREA_API_URL: process.env.AGENTAREA_API_URL,
    AGENTAREA_MCP_APPS_ORIGIN: process.env.AGENTAREA_MCP_APPS_ORIGIN,
    AGENTAREA_APP_ORIGIN: process.env.AGENTAREA_APP_ORIGIN,
  },
  skipValidation: true,
});
