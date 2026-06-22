import type { Metadata } from "next";
import { Login } from "@ory/elements-react/theme";
import { OryPageParams, getFlowFactory } from "@ory/nextjs/app";
import { FlowType, LoginFlow } from "@ory/client-fetch";
// CSS imported via globals.css
import config from "@/ory.config";
import { rewriteFlowForBrowser } from "@/lib/auth/browser-config";
import { serverSideFrontendClient, initOverrides, getPublicUrl } from "@/lib/auth/client";
import { toGetFlowParameter, QueryParams } from "@/lib/auth/utils";

import { AuthLayout } from "@/components/auth/auth-layout";
import { AuthSocialLoadingOverlay } from "@/components/auth/AuthSocialLoadingOverlay";
import { getAuthPageConfig } from "@/lib/auth/page-config";

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
  const loginConfig = getAuthPageConfig();

  return (
    <AuthLayout>
      <AuthSocialLoadingOverlay>
        <Login flow={browserFlow} config={loginConfig} />
      </AuthSocialLoadingOverlay>
    </AuthLayout>
  );
}
