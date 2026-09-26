/**
 * Workspace-scoped endpoints live under `/v1/workspaces/{workspace}/...`.
 * The generated types leave the parameter out, so the transport fills it:
 * the webapp from the page URL, the CLI from `--workspace` or its config.
 *
 * Unfilled, the placeholder stays in the URL as `{workspace}`, or as
 * `%7Bworkspace%7D` once the URL has been through `new Request()`.
 */
const WORKSPACE_PLACEHOLDER = /\{workspace\}|%7Bworkspace%7D/i;

export class MissingWorkspaceError extends Error {
  constructor(readonly path: string) {
    super(
      `${path.replace(new RegExp(WORKSPACE_PLACEHOLDER, "gi"), "{workspace}")} is workspace-scoped and no workspace was selected`
    );
    this.name = "MissingWorkspaceError";
  }
}

// The backend's slug rule. Checked before a slug goes into a path so that
// `..` or an encoded separator can never step out of the workspace segment.
const WORKSPACE_SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const WORKSPACE_SLUG_MAX_LENGTH = 120;

export class InvalidWorkspaceError extends Error {
  constructor(readonly slug: string) {
    super(`${JSON.stringify(slug)} is not a workspace slug`);
    this.name = "InvalidWorkspaceError";
  }
}

/** True when `url` still carries the workspace placeholder in its path. */
export function isWorkspaceScoped(url: string): boolean {
  return WORKSPACE_PLACEHOLDER.test(splitPath(url)[0]);
}

/**
 * Put `slug` into the workspace placeholder of `url`. A URL without one is
 * returned untouched; a URL with one throws on a missing or malformed slug.
 */
export function fillWorkspace(
  url: string,
  slug: string | null | undefined
): string {
  const [path, suffix] = splitPath(url);
  const parts = path.split(new RegExp(WORKSPACE_PLACEHOLDER, "gi"));
  if (parts.length === 1) return url;
  if (!slug) throw new MissingWorkspaceError(path);
  if (slug.length > WORKSPACE_SLUG_MAX_LENGTH || !WORKSPACE_SLUG.test(slug)) {
    throw new InvalidWorkspaceError(slug);
  }
  return parts.join(slug) + suffix;
}

function splitPath(url: string): [string, string] {
  const index = url.search(/[?#]/);
  return index === -1 ? [url, ""] : [url.slice(0, index), url.slice(index)];
}
