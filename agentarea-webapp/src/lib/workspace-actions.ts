"use server";

import { revalidatePath } from "next/cache";
import { cookies } from "next/headers";
import {
  acceptWorkspaceInvitation,
  createWorkspace,
  previewWorkspaceInvitation,
} from "@/lib/api";
import { formatApiError } from "@/lib/api-errors";
import {
  classifyInvitationError,
  type InvitationFailure,
} from "@/lib/invitations";
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

const MISSING_TOKEN: InvitationFailure = {
  problem: "missing_token",
  message: "",
};

function invitationFailure(result: {
  error?: unknown;
  status?: number;
}): InvitationFailure {
  const message = formatApiError(result.error);
  return {
    problem: classifyInvitationError(result.status, message),
    message,
  };
}

export async function previewInvitationAction(token: string) {
  if (!token) {
    return { ok: false as const, error: MISSING_TOKEN };
  }
  const result = await previewWorkspaceInvitation(token);
  if (result.error || !result.data) {
    return { ok: false as const, error: invitationFailure(result) };
  }
  return { ok: true as const, data: result.data };
}

export async function acceptInvitationAction(token: string) {
  if (!token) {
    return { ok: false as const, error: MISSING_TOKEN };
  }
  const result = await acceptWorkspaceInvitation(token);
  if (result.error || !result.data) {
    return { ok: false as const, error: invitationFailure(result) };
  }

  // Joining a workspace is a request to work in it, so it becomes the active one.
  const { workspaces } = await getWorkspaceContext();
  const joined = workspaces.find(
    (workspace) => workspace.id === result.data?.workspace_id
  );
  if (!joined) {
    console.error(
      "[invitation] joined workspace missing from the workspace list:",
      result.data.workspace_id
    );
    return { ok: true as const };
  }
  await setActiveSlug(joined.slug);
  return { ok: true as const };
}
