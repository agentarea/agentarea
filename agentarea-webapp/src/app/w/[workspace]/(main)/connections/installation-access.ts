/**
 * Binding a connection signed in through a GitHub App to one installation of
 * it (`PUT /v1/workspaces/{workspace}/oauth/installation`): its calls then
 * carry a token that reaches only that installation, and only the picked
 * repositories when any are picked.
 */

import type {
  OAuthInstallationBinding,
  OAuthInstallationBindingRequest,
} from "@/api/client";

export type InstallationTarget =
  | { instance_id: string }
  | { openapi_connection_id: string };

/** The Select's value for "no installation": the user's own token. */
export const USER_TOKEN = "user";

/**
 * The request that saves a pick: no installation clears the binding, no
 * repositories means every repository of the installation.
 */
export function bindingRequest(
  target: InstallationTarget,
  installation: string,
  repositories: string[]
): OAuthInstallationBindingRequest {
  if (installation === USER_TOKEN) {
    return { ...target, installation_id: null };
  }
  return {
    ...target,
    installation_id: Number(installation),
    repositories: repositories.length ? repositories : null,
  };
}

/** The Select's value for a binding. */
export function installationValue(
  binding: OAuthInstallationBinding | null | undefined
): string {
  return binding ? String(binding.installation_id) : USER_TOKEN;
}

/**
 * The repositories ticked when an installation's list arrives: the binding's
 * own when it is that installation, and only those the list still has.
 */
export function initialRepositories(
  binding: OAuthInstallationBinding | null | undefined,
  installation: string,
  available: string[]
): string[] {
  if (!binding || String(binding.installation_id) !== installation) return [];
  return (binding.repositories ?? []).filter((r) => available.includes(r));
}

/** Whether the pick differs from what is saved. */
export function bindingChanged(
  binding: OAuthInstallationBinding | null | undefined,
  installation: string,
  repositories: string[]
): boolean {
  if (installationValue(binding) !== installation) return true;
  if (!binding) return false;
  const saved = [...(binding.repositories ?? [])].sort();
  const picked = [...repositories].sort();
  return saved.join("\n") !== picked.join("\n");
}
