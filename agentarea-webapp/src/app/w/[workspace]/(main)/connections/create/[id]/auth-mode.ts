/**
 * How a catalog endpoint wants to be authorized, decided before any connection
 * is created — so the user lands on the right form instead of discovering it
 * after a first "Connect" that already left a broken instance behind.
 */
export type AuthMode =
  | "loading" // probing the endpoint
  | "fields" // spec declares headers → fill them in, validate, create
  | "none" // endpoint is open → Connect creates the instance directly
  | "oauth" // OAuth only (manual entry offered as a fallback link)
  | "credentials" // manual credentials only
  | "both" // OAuth or manual, user picks
  | "error"; // probe failed → retry, or Force create from the subheader

/** The slice of `POST /mcp-server-instances/validate-connection` this reads. */
export interface ValidationOutcome {
  valid: boolean;
  errors?: string[];
  auth_methods?: string[];
}

export function modeFromMethods(methods: string[]): AuthMode {
  const oauth = methods.includes("oauth");
  const credentials = methods.includes("credentials");
  if (oauth && credentials) return "both";
  if (oauth) return "oauth";
  if (credentials) return "credentials";
  return "none";
}

/**
 * A successful listing is not "open": a server may answer tools/list without a
 * token and reject every call. The API reports the OAuth it advertises even on
 * success, and that wins over the listing.
 */
export function authModeFromValidation(outcome: ValidationOutcome): AuthMode {
  const methods = outcome.auth_methods ?? [];
  if (methods.length > 0) return modeFromMethods(methods);
  return outcome.valid ? "none" : "error";
}

/**
 * A spec that declares its own header fields is still probed: a provider such
 * as GitHub documents a token header yet also takes OAuth. When the probe
 * reports OAuth the user gets both, the manual tab showing the declared
 * fields; otherwise only those fields — a failed probe included, since they
 * are enough to connect.
 */
export function withDeclaredFields(mode: AuthMode, hasFields: boolean): AuthMode {
  if (!hasFields || mode === "loading") return mode;
  return mode === "oauth" || mode === "both" ? "both" : "fields";
}
