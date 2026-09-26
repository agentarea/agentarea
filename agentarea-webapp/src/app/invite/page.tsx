import { redirect } from "next/navigation";
import { invitationDialogPath } from "@/lib/invitations";
import { getPersonalWorkspacePath } from "@/lib/workspace-context";

export default async function InvitePage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token } = await searchParams;
  redirect(await getPersonalWorkspacePath(invitationDialogPath(token)));
}
