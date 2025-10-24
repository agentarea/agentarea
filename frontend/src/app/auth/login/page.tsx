import { Login } from "@ory/elements-react/theme";
import { getLoginFlow, OryPageParams } from "@ory/nextjs/app";
import "@ory/elements-react/theme/styles.css";
import config from "@/ory.config";

export default async function LoginPage(props: OryPageParams) {
  const flow = await getLoginFlow(config, props.searchParams);

  if (!flow) {
    return null;
  }

  return (
    <div className="flex min-h-screen items-center justify-center">
      <Login flow={flow} config={config} />
    </div>
  );
}
