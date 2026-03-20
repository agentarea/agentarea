import type { Metadata } from "next";
import { Login } from "@ory/elements-react/theme";
import { OryPageParams, getFlowFactory } from "@ory/nextjs/app";
import { FlowType, LoginFlow } from "@ory/client-fetch";
// CSS imported via globals.css
import config from "@/ory.config";
import { getOryBrowserConfig, rewriteFlowForBrowser } from "@/lib/auth/browser-config";
import { serverSideFrontendClient, initOverrides, getPublicUrl } from "@/lib/auth/client";
import { toGetFlowParameter, QueryParams } from "@/lib/auth/utils";

export const metadata: Metadata = {
  title: "Login",
};

async function getLoginFlow(
  config: { project: { login_ui_url: string } },
  params: QueryParams | Promise<QueryParams>,
): Promise<LoginFlow | null | void> {
  return getFlowFactory(
    await params,
    async () =>
      serverSideFrontendClient().getLoginFlowRaw(
        await toGetFlowParameter(params),
        initOverrides,
      ),
    FlowType.Login,
    await getPublicUrl(),
    config.project.login_ui_url,
  )
}

export default async function LoginPage(props: OryPageParams) {
  const flow = await getLoginFlow(config, props.searchParams);

  if (!flow) {
    return null;
  }

  const browserFlow = rewriteFlowForBrowser(flow);
  const browserConfig = getOryBrowserConfig();
  const loginConfig = {
    ...browserConfig,
    project: {
      ...browserConfig.project,
      logo_light_url: "/logo.svg",
    },
  };

  return (
    <div className="relative flex min-h-screen w-full flex-col sm:items-center sm:justify-center sm:px-4 sm:py-10">
      <div className="pointer-events-none fixed inset-0 bg-background" />
      <div className="pointer-events-none fixed inset-0 bg-[url('/lines.png')] bg-[size:450px_450px] bg-center bg-repeat opacity-20 dark:hidden" />
      <div className="pointer-events-none fixed inset-0 hidden bg-[url('/lines-dark.png')] bg-[size:450px_450px] bg-center bg-repeat opacity-25 dark:block" />

      <div className="login-ory relative z-10 w-full max-w-md my-auto flex flex-col sm:h-auto">
        <Login flow={browserFlow} config={loginConfig} />
      </div>
    </div>
  );
}
