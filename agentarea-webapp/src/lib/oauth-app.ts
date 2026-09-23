/**
 * The OAuth client a workspace brings for providers that cannot register one
 * for us. Mirrors the API's `CustomOAuthAppFields`: exactly one source per
 * credential — typed in, or referenced from a workspace secret.
 */
export type CustomOAuthAppCredentials = {
  client_id?: string;
  client_secret?: string;
  client_id_secret_id?: string;
  client_secret_secret_id?: string;
};
