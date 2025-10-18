import { createEnv } from "@t3-oss/env-nextjs";
import { z } from "zod";

export const env = createEnv({
  server: {
    ORY_ADMIN_URL: z.string().url().default("http://localhost:4434"),
    ORY_SDK_URL: z.string().url().default("http://localhost:4433"),
    API_URL: z.string().url().default("http://localhost:8000"),
  },
  client: {
    // NEXT_PUBLIC_ORY_PUBLIC_URL: z.string().url().optional(),
    // NEXT_PUBLIC_ORY_URL: z.string().url().optional(),
  },
  runtimeEnv: {
    ORY_ADMIN_URL: process.env.ORY_ADMIN_URL,
    ORY_SDK_URL: process.env.ORY_SDK_URL,
    API_URL: process.env.API_URL,
    // NEXT_PUBLIC_ORY_PUBLIC_URL: process.env.NEXT_PUBLIC_ORY_PUBLIC_URL,
    // NEXT_PUBLIC_ORY_URL: process.env.NEXT_PUBLIC_ORY_URL,
  },
  skipValidation: !!process.env.SKIP_ENV_VALIDATION,
});