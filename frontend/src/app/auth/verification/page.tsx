import { Verification } from "@ory/elements-react/theme";
import { getVerificationFlow, OryPageParams } from "@ory/nextjs/app";
import "@ory/elements-react/theme/styles.css";
import config from "@/ory.config";

export default async function VerificationPage(props: OryPageParams) {
  const flow = await getVerificationFlow(config, props.searchParams);

  if (!flow) {
    return null;
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-yellow-600 via-orange-600 to-red-700">
      <div className="w-full max-w-md rounded-xl border border-white/20 bg-white/95 p-8 shadow-2xl backdrop-blur-sm dark:border-gray-700/20 dark:bg-gray-800/95">
        <Verification flow={flow} config={config} />
      </div>
    </div>
  );
}
