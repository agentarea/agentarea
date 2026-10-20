import { redirect } from "next/navigation";
import { oauthFinishAction } from "@/lib/server-actions";

/**
 * Where the API's OAuth callback sends the browser. The code is redeemed here,
 * in the signed-in person's session, so a provider URL someone else started
 * cannot attach this person's account to that someone's connection.
 */
export default async function OAuthFinishPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token } = await searchParams;
  if (!token) {
    redirect(
      `/?${new URLSearchParams({ oauth: "error", reason: "missing_token" })}`
    );
  }
  redirect(await oauthFinishAction(token));
}
