import { createEnv } from "@t3-oss/env-nextjs";
import { z } from "zod";

export const env = createEnv({
  server: {
    ORY_ADMIN_URL: z.string().url(),
    ORY_SDK_URL: z.string().url(),
    ORY_BROWSER_URL: z.string().url().optional(),
    API_URL: z.string().url(),
  },
  client: {},
  runtimeEnv: {
    ORY_ADMIN_URL: process.env.ORY_ADMIN_URL,
    ORY_SDK_URL: process.env.ORY_SDK_URL,
    ORY_BROWSER_URL: process.env.ORY_BROWSER_URL,
    API_URL: process.env.API_URL,
  },
  skipValidation: true,
});
