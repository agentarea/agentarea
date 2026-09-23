import { redirect } from "next/navigation";
import {
  AccountExperienceConfiguration,
  FlowType,
  handleFlowError,
} from "@ory/client-fetch";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { serverSideFrontendClient } from "./client";
import {
  getLoginFlow,
  getRecoveryFlow,
  getRegistrationFlow,
  getVerificationFlow,
} from "./flows";
import { getPublicUrl } from "./request";

vi.mock("server-only", () => ({}));

vi.mock("./request", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./request")>();
  return {
    ...actual,
    getPublicUrl: vi.fn(),
    toGetFlowParameter: vi.fn((params: unknown) => params),
  };
});

vi.mock("./client", () => ({
  serverSideFrontendClient: vi.fn().mockReturnValue({
    getLoginFlowRaw: vi.fn(),
    getRegistrationFlowRaw: vi.fn(),
    getRecoveryFlowRaw: vi.fn(),
    getVerificationFlowRaw: vi.fn(),
  }),
}));

vi.mock("next/navigation", () => ({
  redirect: vi.fn(),
  RedirectType: { replace: "replace" },
}));

vi.mock("@ory/client-fetch", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@ory/client-fetch")>();
  return {
    ...actual,
    handleFlowError: vi.fn(),
  };
});

const config = {
  project: {
    registration_enabled: true,
    verification_enabled: true,
    recovery_enabled: true,
    recovery_ui_url: "/auth/recovery",
    registration_ui_url: "/auth/registration",
    verification_ui_url: "/auth/verification",
    login_ui_url: "/auth/login",
    settings_ui_url: "/settings",
    default_redirect_url: "/",
    logo_light_url: "/logo.svg",
    logo_dark_url: "/logo-dark.svg",
    error_ui_url: "/auth/error",
    name: "AgentArea",
    default_locale: "en",
    enabled_locales: ["en"],
    locale_behavior: "force_default",
    translations: [],
  } satisfies AccountExperienceConfiguration,
};

beforeEach(() => {
  vi.clearAllMocks();
  process.env.ORY_SDK_URL = "https://ory.sh/";
  vi.mocked(getPublicUrl).mockResolvedValue("https://example.com");
  vi.mocked(handleFlowError).mockReturnValue(async () => undefined);
});

const testCases = [
  { fn: getLoginFlow, flowType: FlowType.Login, raw: "getLoginFlowRaw" },
  {
    fn: getRegistrationFlow,
    flowType: FlowType.Registration,
    raw: "getRegistrationFlowRaw",
  },
  {
    fn: getRecoveryFlow,
    flowType: FlowType.Recovery,
    raw: "getRecoveryFlowRaw",
  },
  {
    fn: getVerificationFlow,
    flowType: FlowType.Verification,
    raw: "getVerificationFlowRaw",
  },
] as const;

for (const tc of testCases) {
  describe(`flowType=${tc.flowType}`, () => {
    const rawMock = () =>
      vi.mocked(
        serverSideFrontendClient() as unknown as Record<
          string,
          ReturnType<typeof vi.fn>
        >
      )[tc.raw];

    test("restarts the flow when no id is given", async () => {
      await tc.fn(config, {});
      expect(redirect).toHaveBeenCalledWith(
        `https://example.com/self-service/${tc.flowType}/browser?`,
        "replace"
      );
    });

    test("carries query params into the restarted flow", async () => {
      await tc.fn(config, { refresh: "true" });
      expect(redirect).toHaveBeenCalledWith(
        `https://example.com/self-service/${tc.flowType}/browser?refresh=true`,
        "replace"
      );
    });

    test("fetches the flow and rewrites Ory URLs to the public origin", async () => {
      rawMock().mockResolvedValue({
        value: vi.fn().mockResolvedValue({
          foo: "https://ory.sh/a",
          bar: "https://ory.sh/",
        }),
      });

      await expect(tc.fn(config, { flow: "1234" })).resolves.toEqual({
        foo: "https://example.com/a",
        bar: "https://example.com/",
      });
    });

    test("delegates to the Ory error handler on failure", async () => {
      rawMock().mockRejectedValue(new Error("boom"));

      await expect(tc.fn(config, { flow: "1234" })).resolves.toBeUndefined();
      expect(handleFlowError).toHaveBeenCalled();
    });
  });
}
