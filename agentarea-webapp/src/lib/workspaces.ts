export const WORKSPACE_SLUG_COOKIE = "workspace_slug";
export const WORKSPACE_SLUG_HEADER = "x-workspace-slug";

export type Workspace = {
  id: string;
  slug: string;
  name: string;
  owner_user_id: string;
};

/**
 * A workspace auto-provisioned for a single user, recognised by its id being
 * that user's own id.
 *
 * Derived rather than read from a ``type`` field: the backend used to store
 * that alongside the id it described, which is one copy too many. Owning a
 * workspace is not the same thing — you own every workspace you create.
 */
export function isPersonalWorkspace(workspace: Workspace): boolean {
  return workspace.id === workspace.owner_user_id;
}

/**
 * Pick the workspace a request should run against.
 *
 * The preferred slug comes from the switcher cookie and is deliberately not
 * trusted: a user who left a workspace keeps the cookie, and sending a slug
 * they are no longer a member of makes the backend reject every request. An
 * unrecognised slug therefore falls back to the personal workspace, which the
 * backend provisions for every user.
 */
export function resolveActiveWorkspace<T extends Workspace>(
  workspaces: T[],
  preferredSlug: string | null | undefined
): T | null {
  if (workspaces.length === 0) return null;

  if (preferredSlug) {
    const match = workspaces.find((w) => w.slug === preferredSlug);
    if (match) return match;
  }

  return workspaces.find(isPersonalWorkspace) ?? workspaces[0];
}
