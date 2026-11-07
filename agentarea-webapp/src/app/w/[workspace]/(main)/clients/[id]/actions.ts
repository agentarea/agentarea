"use server";

import { revalidatePath } from "next/cache";
import { issueRunnerKey, revokeRunnerKey, updateClient } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { requestWorkspacePath } from "@/lib/workspace-request";

async function revalidateClient(clientId: string) {
  revalidatePath(await requestWorkspacePath(`/clients/${clientId}`));
}

export async function setRunnerModelAction(
  clientId: string,
  model: string
): Promise<{ error: string | null }> {
  const result = await updateClient(clientId, { default_model: model });
  if (result.error) {
    return { error: apiErrorMessage(result, "The model could not be saved") };
  }
  await revalidateClient(clientId);
  return { error: null };
}

/** The hosts from the form's textarea, one per line or comma-separated. */
export async function saveAllowDomainsAction(
  clientId: string,
  _previous: { error: string | null },
  form: FormData
): Promise<{ error: string | null }> {
  const domains = String(form.get("allow_domains") ?? "")
    .split(/[\s,]+/)
    .map((domain) => domain.trim())
    .filter(Boolean);
  const result = await updateClient(clientId, { allow_domains: domains });
  if (result.error) {
    return { error: apiErrorMessage(result, "The domains could not be saved") };
  }
  await revalidateClient(clientId);
  return { error: null };
}

/** A new key for the client's runner; the key is in the result only, once. */
export async function issueRunnerKeyAction(
  clientId: string
): Promise<{ error: string; key?: undefined } | { error: null; key: string }> {
  const result = await issueRunnerKey(clientId);
  if (!result.data) {
    return {
      error: apiErrorMessage(result, "The runner key could not be issued"),
    };
  }
  return { error: null, key: result.data.key };
}

export async function revokeRunnerKeyAction(
  clientId: string,
  keyId: string
): Promise<{ error: string | null }> {
  const result = await revokeRunnerKey(clientId, keyId);
  if (result.error) {
    return {
      error: apiErrorMessage(result, "The runner key could not be revoked"),
    };
  }
  await revalidateClient(clientId);
  return { error: null };
}
