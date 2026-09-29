import { redirect } from "next/navigation";
import { workspacePath } from "@/lib/workspace-routes";

/** The page moved to /models, which is what the sidebar has always called it. */
export default async function ProviderConfigsRedirect({
  params,
}: {
  params: Promise<{ workspace: string }>;
}) {
  const { workspace } = await params;
  redirect(workspacePath(workspace, "/models"));
}
