"use server";

import { redirect } from "next/navigation";
import { zOAuthConsentDecision } from "@/api/client/zod.gen";
import { decideOAuthConsent } from "@/lib/api";

export type ConsentState = { error: "acceptFailed" | "rejectFailed" } | null;

/** Accept or reject the consent request; on success the browser goes where Hydra says. */
export async function decideConsent(
  _previous: ConsentState,
  form: FormData
): Promise<ConsentState> {
  const workspaces = form
    .getAll("workspaces")
    .filter((slug): slug is string => typeof slug === "string" && slug !== "");
  const parsed = zOAuthConsentDecision.safeParse({
    challenge: form.get("challenge"),
    action: form.get("action"),
    workspaces: workspaces.length > 0 ? workspaces : null,
  });
  if (!parsed.success) {
    return { error: "acceptFailed" };
  }
  const { data, error } = await decideOAuthConsent(parsed.data);
  if (error || !data) {
    console.error("[auth/consent] decision refused:", error);
    return {
      error: parsed.data.action === "reject" ? "rejectFailed" : "acceptFailed",
    };
  }
  redirect(data.redirect_to);
}
