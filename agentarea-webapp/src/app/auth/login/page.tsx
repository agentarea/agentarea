import { Login } from "@ory/elements-react/theme";
import { OryPageParams, getFlowFactory } from "@ory/nextjs/app";
import "@ory/elements-react/theme/styles.css";
import config from "@/ory.config";
import { env } from "@/env";

import { FlowType, LoginFlow } from "@ory/client-fetch"
import { serverSideFrontendClient, initOverrides, getPublicUrl } from "@/lib/auth/client";
import { toGetFlowParameter, QueryParams } from "@/lib/auth/utils";

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

  // TODO: replace workaround for local kratos URL mapping when using proper service configuration
  let modifiedFlow = flow;
  if (flow && flow.ui && typeof flow.ui.action === "string") {
    modifiedFlow = {
      ...flow,
      ui: {
        ...flow.ui,
        action: flow.ui.action.replace(env.ORY_SDK_URL, env.NEXT_PUBLIC_ORY_SDK_URL ?? ""),
      },
    };
  }

  return (
    <div className="flex min-h-screen items-center justify-center">
      <Login flow={modifiedFlow} config={config} />
    </div>
  );
}
