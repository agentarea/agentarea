import { redirect } from "next/navigation";
import { WORKSPACE_HOME, workspacePath } from "@/lib/workspace-routes";

export default async function WorkspaceHome({
  params,
}: {
  params: Promise<{ workspace: string }>;
}) {
  const { workspace } = await params;
  redirect(workspacePath(workspace, WORKSPACE_HOME));
}
