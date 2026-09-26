import { notFound } from "next/navigation";
import { getWorkspaces } from "@/lib/workspace-context";

/**
 * The URL names the workspace. A slug the caller is not a member of is a
 * missing page, never a silent switch to another workspace.
 */
export default async function WorkspaceLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ workspace: string }>;
}) {
  const [{ workspace }, workspaces] = await Promise.all([
    params,
    getWorkspaces(),
  ]);
  if (!workspaces.some((candidate) => candidate.slug === workspace)) {
    notFound();
  }
  return children;
}
