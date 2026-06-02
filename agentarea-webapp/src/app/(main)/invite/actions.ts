"use server";

import { acceptWorkspaceInvitation } from "@/lib/api";

function errMsg(error: unknown, fallback: string): string {
  const e = error as { detail?: unknown };
  if (Array.isArray(e?.detail)) {
    return (e.detail[0] as { msg?: string })?.msg || fallback;
  }
  if (typeof e?.detail === "string") return e.detail;
  return fallback;
}

export async function acceptInvitationAction(token: string) {
  if (!token) return { error: "Missing invitation token" };
  const { data, error } = await acceptWorkspaceInvitation(token);
  if (error) return { error: errMsg(error, "Failed to accept invitation") };
  return { data };
}
