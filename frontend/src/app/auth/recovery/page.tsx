// Copyright © 2024 Ory Corp

import { Recovery } from "@ory/elements-react/theme";
import { getRecoveryFlow, OryPageParams } from "@ory/nextjs/app";
import "@ory/elements-react/theme/styles.css";
import config from "@/ory.config";

export default async function RecoveryPage(props: OryPageParams) {
  const flow = await getRecoveryFlow(config, props.searchParams);

  if (!flow) {
    return null;
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-green-600 via-blue-600 to-purple-700">
      <div className="w-full max-w-md rounded-xl border border-white/20 bg-white/95 p-8 shadow-2xl backdrop-blur-sm dark:border-gray-700/20 dark:bg-gray-800/95">
        <Recovery flow={flow} config={config} />
      </div>
    </div>
  );
}
