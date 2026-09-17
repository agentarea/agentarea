import { OryClientConfiguration } from "@ory/elements-react";
import { getOryBrowserConfig } from "@/lib/auth/browser-config";

export const getAuthPageConfig = async (): Promise<OryClientConfiguration> => {
  const browserConfig = await getOryBrowserConfig();
  return {
    ...browserConfig,
    project: {
      ...browserConfig.project,
      logo_light_url: "/logo.svg",
      logo_dark_url: "/logo-dark.svg",
    },
  };
};
