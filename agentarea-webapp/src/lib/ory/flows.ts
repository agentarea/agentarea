// Copyright © 2024 Ory Corp
// SPDX-License-Identifier: Apache-2.0
//
// Derived from @ory/nextjs (Apache-2.0).

import "server-only";
import { headers } from "next/headers";
import { redirect, RedirectType } from "next/navigation";
import {
  ApiResponse,
  FlowType,
  handleFlowError,
  LoginFlow,
  LogoutFlow,
  RecoveryFlow,
  RegistrationFlow,
  Session,
  SettingsFlow,
  VerificationFlow,
} from "@ory/client-fetch";
import { serverSideFrontendClient } from "./client";
import {
  getCookieHeader,
  getPublicUrl,
  onRedirect,
  startNewFlow,
  toGetFlowParameter,
} from "./request";
import { rewriteJsonResponse } from "./rewrite";
import { initOverrides, type QueryParams } from "./types";

function onValidationError<T>(value: T): T {
  return value;
}

/**
 * Fetches an existing self-service flow, or restarts it when the flow id is
 * missing or expired.
 *
 * Unless you are building something very custom, prefer the `get*Flow` helpers
 * below.
 */
export async function getFlowFactory<T extends object>(
  params: QueryParams,
  fetchFlowRaw: () => Promise<ApiResponse<T>>,
  flowType: FlowType,
  baseUrl: string,
  route: string,
  options: {
    disableRewrite?: boolean;
  } = { disableRewrite: false }
): Promise<T | null | void> {
  const onRestartFlow = (useFlowId?: string) => {
    if (!useFlowId) {
      return startNewFlow(params, flowType, baseUrl);
    }

    const redirectTo = new URL(route, baseUrl);
    redirectTo.search = new URLSearchParams({
      ...params,
      flow: useFlowId,
    }).toString();
    return redirect(redirectTo.toString(), RedirectType.replace);
  };

  if (!params["flow"]) {
    return onRestartFlow();
  }

  try {
    const rawResponse = await fetchFlowRaw();
    return await rawResponse
      .value()
      .then(
        (v: T): T =>
          options.disableRewrite ? v : rewriteJsonResponse(v, baseUrl)
      );
  } catch (error) {
    const errorHandler = handleFlowError({
      onValidationError,
      onRestartFlow,
      onRedirect,
    });

    return await errorHandler(error);
  }
}

export async function getLoginFlow(
  config: { project: { login_ui_url: string } },
  params: QueryParams | Promise<QueryParams>
): Promise<LoginFlow | null | void> {
  return getFlowFactory(
    await params,
    async () =>
      serverSideFrontendClient().getLoginFlowRaw(
        await toGetFlowParameter(params),
        initOverrides
      ),
    FlowType.Login,
    await getPublicUrl(),
    config.project.login_ui_url
  );
}

export async function getRegistrationFlow(
  config: { project: { registration_ui_url: string } },
  params: QueryParams | Promise<QueryParams>
): Promise<RegistrationFlow | null | void> {
  return getFlowFactory(
    await params,
    async () =>
      serverSideFrontendClient().getRegistrationFlowRaw(
        await toGetFlowParameter(params),
        initOverrides
      ),
    FlowType.Registration,
    await getPublicUrl(),
    config.project.registration_ui_url
  );
}

export async function getRecoveryFlow(
  config: { project: { recovery_ui_url: string } },
  params: QueryParams | Promise<QueryParams>
): Promise<RecoveryFlow | null | void> {
  return getFlowFactory(
    await params,
    async () =>
      serverSideFrontendClient().getRecoveryFlowRaw(
        await toGetFlowParameter(params),
        initOverrides
      ),
    FlowType.Recovery,
    await getPublicUrl(),
    config.project.recovery_ui_url
  );
}

export async function getVerificationFlow(
  config: { project: { verification_ui_url: string } },
  params: QueryParams | Promise<QueryParams>
): Promise<VerificationFlow | null | void> {
  return getFlowFactory(
    await params,
    async () =>
      serverSideFrontendClient().getVerificationFlowRaw(
        await toGetFlowParameter(params),
        initOverrides
      ),
    FlowType.Verification,
    await getPublicUrl(),
    config.project.verification_ui_url
  );
}

export async function getSettingsFlow(
  config: { project: { settings_ui_url: string } },
  params: QueryParams | Promise<QueryParams>
): Promise<SettingsFlow | null | void> {
  return getFlowFactory(
    await params,
    async () =>
      serverSideFrontendClient().getSettingsFlowRaw(
        await toGetFlowParameter(params),
        initOverrides
      ),
    FlowType.Settings,
    await getPublicUrl(),
    config.project.settings_ui_url
  );
}

export async function getLogoutFlow({
  returnTo,
}: { returnTo?: string } = {}): Promise<LogoutFlow> {
  const h = await headers();
  const url = await getPublicUrl();

  return serverSideFrontendClient()
    .createBrowserLogoutFlow({
      cookie: h.get("cookie") ?? "",
      returnTo,
    })
    .then((v: LogoutFlow): LogoutFlow => rewriteJsonResponse(v, url));
}

export async function getServerSession(): Promise<Session | null> {
  const cookie = await getCookieHeader();
  return serverSideFrontendClient()
    .toSession({
      cookie,
    })
    .catch(() => null);
}
