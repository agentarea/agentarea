import { createEnv } from "@t3-oss/env-nextjs";
import { z } from "zod";

export const env = createEnv({
  server: {
    ORY_ADMIN_URL: z.string().url(),
    ORY_SDK_URL: z.string().url(),
    API_URL: z.string().url(),
  },
  client: {
    NEXT_PUBLIC_ORY_SDK_URL: z.string().url().optional(),
  },
  runtimeEnv: {
    ORY_ADMIN_URL: process.env.ORY_ADMIN_URL,
    ORY_SDK_URL: process.env.ORY_SDK_URL,
    API_URL: process.env.API_URL,
    NEXT_PUBLIC_ORY_SDK_URL: process.env.NEXT_PUBLIC_ORY_SDK_URL,
  },
  skipValidation: true,
});
