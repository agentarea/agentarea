// Copyright © 2024 Ory Corp

import { Settings } from "@ory/elements-react/theme"
import { SessionProvider } from "@ory/elements-react/client"
import { getSettingsFlow, OryPageParams } from "@ory/nextjs/app"
import "@ory/elements-react/theme/styles.css"

import config from "@/ory.config"

export default async function SettingsPage(props: OryPageParams) {
  const flow = await getSettingsFlow(config, props.searchParams)

  if (!flow) {
    return null
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-purple-600 via-blue-600 to-indigo-700">
      <div className="w-full max-w-md p-8 bg-white/95 dark:bg-gray-800/95 shadow-2xl rounded-xl backdrop-blur-sm border border-white/20 dark:border-gray-700/20">
        <SessionProvider>
          <Settings flow={flow} config={config} />
        </SessionProvider>
      </div>
    </div>
  )
}