// Copyright © 2025 Ory Corp
// SPDX-License-Identifier: Apache-2.0

import { createContext, PropsWithChildren, useContext, useRef } from "react"
import { isProduction } from "../client/config"
import { OryClientConfiguration } from "../util"
import { frontendClient } from "../util/client"
import {
  AccountExperienceConfiguration,
  ConfigurationParameters,
  FrontendApi,
} from "@ory/client-fetch"

/**
 * The Ory Elements configuration object.
 *
 * @interface
 */
export type OryElementsConfiguration = {
  /**
   * The Ory SDK configuration.
   * This includes the URL and options for the Ory SDK.
   */
  sdk: OrySDK
  /**
   * The project configuration.
   * This includes the project name, URLs, and other settings for the Ory Elements project.
   */
  project: AccountExperienceConfiguration
}

const defaultProject: AccountExperienceConfiguration = {
  name: "Ory",
  registration_enabled: true,
  verification_enabled: true,
  recovery_enabled: true,
  recovery_ui_url: "/ui/recovery",
  registration_ui_url: "/ui/registration",
  verification_ui_url: "/ui/verification",
  login_ui_url: "/ui/login",
  settings_ui_url: "/ui/settings",
  default_redirect_url: "/ui/welcome",
  error_ui_url: "/ui/error",
  default_locale: "en",
  locale_behavior: "force_default",
}

/**
 * The `useOryConfiguration` hook provides access to the Ory Elements configuration.
 *
 * This includes the SDK configuration and the project configuration. To customize the configuration, provide the `sdk` and `project` properties in the `OryConfigurationProvider`.
 *
 * @returns the Ory Elements configuration, which includes the SDK and project configuration.
 * @group Hooks
 */
export function useOryConfiguration(): OryElementsConfiguration {
  const configCtx = useContext(OryConfigurationContext)
  return {
    sdk: {
      ...configCtx.sdk,
      frontend: frontendClient(configCtx.sdk.url, configCtx.sdk.options),
    },
    project: {
      ...configCtx.project,
    },
  }
}

export type OrySDK = SDKConfig & {
  /**
   * The frontend client for the Ory SDK.
   * This client is used to interact with the Ory SDK and should be used to make API calls.
   */
  frontend: FrontendApi
}

type SDKConfig = {
  /**
   * The URL of the Ory SDK.
   * This URL is used to connect to the Ory SDK and should be set to the base URL of your Ory instance.
   */
  url: string
  options?: Partial<ConfigurationParameters>
}

type OryElementsConfigContextType = {
  sdk: SDKConfig
  project: AccountExperienceConfiguration
}

const OryConfigurationContext = createContext<OryElementsConfigContextType>({
  sdk: null!, // This is fine, because we always supply a proper default value for the SDK configuration in the provider
  project: defaultProject,
})

/**
 * Props for the `OryConfigurationProvider` component.
 *
 * @hidden
 * @inline
 */
export interface OryConfigurationProviderProps extends PropsWithChildren {
  /**
   * The Ory SDK configuration to use.
   * If not provided, the SDK URL will be determined automatically based on the environment.
   *
   * Always required for production environments.
   */
  sdk?: OryClientConfiguration["sdk"]

  /**
   * This configuration is used to customize the behavior and appearance of Ory Elements.
   */
  project?: Partial<AccountExperienceConfiguration>
}

/**
 * The `OryConfigurationProvider` component provides the Ory Elements configuration to its children.
 *
 * @param props - The properties for the OryConfigurationProvider component.
 * @returns
 * @group Components
 */
export function OryConfigurationProvider({
  children,
  sdk: initialConfig,
  project,
}: OryConfigurationProviderProps) {
  const configRef = useRef({
    sdk: computeSdkConfig(initialConfig),
    project: {
      ...defaultProject,
      ...project,
    },
  })

  return (
    <OryConfigurationContext.Provider value={configRef.current}>
      {children}
    </OryConfigurationContext.Provider>
  )
}

function computeSdkConfig(config?: OryClientConfiguration["sdk"]): SDKConfig {
  if (config?.url && typeof config.url === "string") {
    return {
      url: config.url.replace(/\/$/, ""),
      options: config.options || {},
    }
  }

  return {
    url: getSDKUrl(),
    options: config?.options || {},
  }
}

function getSDKUrl() {
  // 1. Check runtime config injected via window.__ENV__ (works in browser at runtime)
  if (typeof window !== "undefined") {
    const runtimeEnv = (window as any).__ENV__ || {};
    if (runtimeEnv.CLIENT_ORY_SDK_URL) {
      return runtimeEnv.CLIENT_ORY_SDK_URL.replace(/\/$/, "");
    }
  }

  // 2. Check server-side env vars (works during SSR)
  if (typeof process !== "undefined" && !!process.env) {
    if (process.env.ORY_SDK_URL) {
      return process.env.ORY_SDK_URL.replace(/\/$/, "");
    }

    // Development helpers
    if (!isProduction()) {
      if (process.env["__NEXT_PRIVATE_ORIGIN"]) {
        return process.env["__NEXT_PRIVATE_ORIGIN"].replace(/\/$/, "");
      } else if (process.env["VERCEL_URL"]) {
        return `https://${process.env["VERCEL_URL"]}`.replace(/\/$/, "");
      }
    }
  }

  // 3. Fallback: use window.location.origin in browser (for same-origin setups)
  if (typeof window !== "undefined") {
    return window.location.origin;
  }

  // 4. No way to determine URL
  throw new Error(
    "Unable to determine SDK URL. Please set CLIENT_ORY_SDK_URL in window.__ENV__ (client-side) or ORY_SDK_URL (server-side), or supply the sdk.url parameter in the Ory configuration.",
  );
}
