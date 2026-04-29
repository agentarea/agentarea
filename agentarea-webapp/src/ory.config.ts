import type { OryClientConfiguration } from "@ory/elements-react";

const config: OryClientConfiguration = {
  sdk: {
    url:
      typeof window !== "undefined"
        ? (window as any).__ENV__?.CLIENT_ORY_SDK_URL
        : process.env.ORY_SDK_URL,
  },
  project: {
    default_locale: "en",
    default_redirect_url: "/",
    enabled_locales: ["en"],
    error_ui_url: "/auth/error",
    locale_behavior: "force_default",
    name: "AgentArea",
    registration_enabled: true,
    verification_enabled: true,
    recovery_enabled: true,
    registration_ui_url: "/auth/registration",
    verification_ui_url: "/auth/verification",
    recovery_ui_url: "/auth/recovery",
    login_ui_url: "/auth/login",
    settings_ui_url: "/settings",
    translations: [],
  },
};

export default config;
