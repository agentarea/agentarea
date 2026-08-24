"use server";

import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import { createWorkspace } from "@/lib/api";
import { getWorkspaceContext } from "@/lib/workspace-context";
import { WORKSPACE_SLUG_COOKIE } from "@/lib/workspaces";

const ONE_YEAR_SECONDS = 60 * 60 * 24 * 365;

async function setActiveSlug(slug: string) {
  const cookieStore = await cookies();
  cookieStore.set(WORKSPACE_SLUG_COOKIE, slug, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: ONE_YEAR_SECONDS,
  });
  // Every page's data is workspace-scoped, so switching invalidates the whole
  // cached tree, not one route.
  revalidatePath("/", "layout");
}

export async function switchWorkspaceAction(slug: string) {
  // Never persist a slug the backend would reject: the cookie is sent with
  // every subsequent request, so a bad one breaks the whole session.
  const { workspaces } = await getWorkspaceContext();
  if (!workspaces.some((workspace) => workspace.slug === slug)) {
    return { error: "You are not a member of that workspace" };
  }

  await setActiveSlug(slug);
  return { ok: true };
}

export async function createWorkspaceAction(name: string) {
  const trimmed = name.trim();
  if (!trimmed) return { error: "Workspace name must not be empty" };

  const { data, error } = await createWorkspace(trimmed);
  if (error || !data) {
    const detail = (error as { detail?: unknown })?.detail;
    return {
      error: typeof detail === "string" ? detail : "Failed to create workspace",
    };
  }

  await setActiveSlug(data.slug);
  return { data };
}
