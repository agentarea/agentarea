import { redirect } from "next/navigation";
import { invitationDialogPath } from "@/lib/invitations";

export default async function InvitePage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token } = await searchParams;
  redirect(invitationDialogPath(token));
}
