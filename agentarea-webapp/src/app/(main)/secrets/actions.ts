"use server";

import { revalidatePath } from "next/cache";
import type { SecretResponse } from "@/api/client/types.gen";
import { createSecret, deleteSecret, rotateSecret } from "@/lib/api";

type ActionResult = { error: string | null };

/** The created secret rides along, so a picker can select what was just made. */
export type CreateSecretResult =
  | { error: string; secret?: undefined }
  | { error: null; secret: SecretResponse };

/** Pull the server's own message out, so a rejected name or a 409 explains itself. */
function messageFrom(error: unknown, fallback: string): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string };
    if (first?.msg) return first.msg;
  }
  if (detail && typeof detail === "object") {
    const message = (detail as { message?: string }).message;
    if (message) return message;
  }
  return fallback;
}

export async function createSecretAction(input: {
  name: string;
  value: string;
  description?: string;
}): Promise<CreateSecretResult> {
  const { data, error } = await createSecret({
    name: input.name,
    value: input.value,
    description: input.description || null,
  });
  if (error) {
    return { error: messageFrom(error, "Could not create the secret") };
  }
  if (!data) {
    // Callers select the secret they just made; a create that answers with
    // nothing would leave them picking from a list they can't search by value.
    return { error: "The secret was created but the server returned nothing." };
  }
  revalidatePath("/secrets");
  return { error: null, secret: data };
}

export async function rotateSecretAction(
  secretId: string,
  value: string
): Promise<ActionResult> {
  const { error } = await rotateSecret(secretId, value);
  if (error) {
    return { error: messageFrom(error, "Could not update the secret") };
  }
  revalidatePath("/secrets");
  return { error: null };
}

export async function deleteSecretAction(
  secretId: string
): Promise<ActionResult> {
  const { error } = await deleteSecret(secretId);
  if (error) {
    // A 409 carries the list of things still resolving this secret; surfacing
    // the server's message is what tells the user where to go and detach it.
    return { error: messageFrom(error, "Could not delete the secret") };
  }
  revalidatePath("/secrets");
  return { error: null };
}
