// The egress exit form's values and how they become the API's request bodies.
// No React here: the dialog and the server actions share it.

import type {
  EgressExitCreate,
  EgressExitResponse,
  EgressExitUpdate,
} from "@/api/client/types.gen";

/** What the form edits. Optional text is "" until filled; "" secret is none. */
export type EgressExitFormValues = {
  name: string;
  description: string;
  upstream_url: string;
  username: string;
  password_secret_id: string;
  allow_plaintext_credentials: boolean;
};

export function emptyEgressExitForm(): EgressExitFormValues {
  return {
    name: "",
    description: "",
    upstream_url: "",
    username: "",
    password_secret_id: "",
    allow_plaintext_credentials: false,
  };
}

export function egressExitToForm(
  exit: EgressExitResponse
): EgressExitFormValues {
  return {
    name: exit.name,
    description: exit.description ?? "",
    upstream_url: exit.upstream_url ?? "",
    username: exit.username ?? "",
    password_secret_id: exit.password_secret_id ?? "",
    allow_plaintext_credentials: exit.allow_plaintext_credentials,
  };
}

const optional = (value: string) => value.trim() || null;

export function toEgressExitCreate(
  form: EgressExitFormValues
): EgressExitCreate {
  return {
    name: form.name.trim(),
    description: optional(form.description),
    upstream_url: form.upstream_url.trim(),
    username: optional(form.username),
    password_secret_id: optional(form.password_secret_id),
    allow_plaintext_credentials:
      sendsPlaintextCredentials(form) && form.allow_plaintext_credentials,
  };
}

/**
 * Every editable field, so clearing one (the username, the password) clears
 * it on the server: an explicit null there means "none".
 */
export function toEgressExitUpdate(
  form: EgressExitFormValues
): EgressExitUpdate {
  return toEgressExitCreate(form);
}

/**
 * Credentials sent to an http or socks5 proxy cross the network unencrypted;
 * the API refuses them unless the form says it is meant.
 */
export function sendsPlaintextCredentials(
  form: Pick<EgressExitFormValues, "upstream_url" | "username">
): boolean {
  const scheme = form.upstream_url.trim().split("://")[0]?.toLowerCase();
  return form.username.trim() !== "" && scheme !== "https";
}
