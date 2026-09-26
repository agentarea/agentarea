"use server";

import { revalidatePath } from "next/cache";
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
import { getWorkspaces } from "@/lib/workspace-context";

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

  // The switcher in the root layout lists workspaces.
  revalidatePath("/", "layout");
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

  // Joining a workspace is a request to work in it: the caller navigates there.
  const joined = (await getWorkspaces()).find(
    (workspace) => workspace.id === result.data?.workspace_id
  );
  if (!joined) {
    throw new Error(
      `Joined workspace ${result.data.workspace_id} is missing from the workspace list`
    );
  }
  revalidatePath("/", "layout");
  return { ok: true as const, slug: joined.slug };
}
