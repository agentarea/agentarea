// Token validation cost: an authenticated no-op (GET /v1/workspaces — the
// lightest authenticated read there is, no workspace-scoped repository
// query) against the unauthenticated /health floor. The gap between the two
// is roughly what auth costs on every request.
import { group } from "k6";
import { BASE_URL } from "../config.js";
import { get, getPublic } from "../http.js";
import { tag } from "./tags.js";

export const authJourney = {
  name: "auth",
  run: () => {
    group("journey: auth", () => {
      getPublic(`${BASE_URL}/health`, "health", tag("auth", "health"));
      get(`${BASE_URL}/v1/workspaces`, "authed_noop", tag("auth", "authed_noop"));
    });
  },
};
