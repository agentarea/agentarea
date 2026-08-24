export const WORKSPACE_SLUG_COOKIE = "workspace_slug";
export const WORKSPACE_SLUG_HEADER = "x-workspace-slug";

export type Workspace = {
  id: string;
  slug: string;
  name: string;
  type: string;
};

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

  return workspaces.find((w) => w.type === "personal") ?? workspaces[0];
}
