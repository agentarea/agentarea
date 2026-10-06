import {
  stripWorkspacePrefix,
  workspacePath,
  workspaceSlugFromPath,
} from "@/lib/workspace-routes";

/**
 * Opening /settings without a Kratos flow is a round trip: the browser fetches
 * a new flow from Kratos, and Kratos sends it back to its configured ui_url,
 * `/settings`, outside any workspace. Rendered as pages, each hop paints the
 * whole app shell and then redirects from inside it — three full page loads.
 * proxy.ts answers both hops as plain redirects before anything renders, and
 * remembers in this cookie which workspace the trip started from, so the flow
 * comes back there rather than to the personal workspace.
 */
export const SETTINGS_RETURN_COOKIE = "aa_settings_workspace";

export type SettingsHop =
  /** `/w/{slug}/settings` with no flow: get one from Kratos. */
  | { kind: "to-kratos"; location: string; workspace: string }
  /** Kratos' `/settings?flow=…`: back into the workspace the trip began in. */
  | { kind: "to-workspace"; location: string }
  | null;

export function settingsEntryHop(
  url: URL,
  {
    kratosBrowserUrl,
    returnWorkspace,
  }: { kratosBrowserUrl: string; returnWorkspace?: string }
): SettingsHop {
  const slug = workspaceSlugFromPath(url.pathname);

  if (slug && stripWorkspacePrefix(url.pathname) === "/settings") {
    if (url.searchParams.has("flow")) return null;
    const location = new URL(
      "/self-service/settings/browser",
      kratosBrowserUrl
    );
    location.search = url.search;
    return {
      kind: "to-kratos",
      location: location.toString(),
      workspace: slug,
    };
  }

  if (
    url.pathname === "/settings" &&
    url.searchParams.has("flow") &&
    returnWorkspace
  ) {
    return {
      kind: "to-workspace",
      location: `${workspacePath(returnWorkspace, "/settings")}${url.search}`,
    };
  }

  return null;
}
