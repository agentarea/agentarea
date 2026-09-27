// Every resource a write journey creates carries this prefix so the janitor
// (janitor.js) can find and delete it later — including a leftover from a run
// that crashed before it could clean up after itself.
import { TESTID } from "../config.js";

export const RESOURCE_PREFIX = "k6-";

export function resourceName(kind) {
  // __VU/__ITER keep two VUs creating the same kind in the same iteration
  // window from colliding on a unique-per-workspace name field.
  return `${RESOURCE_PREFIX}${TESTID}-${kind}-${__VU}-${__ITER}-${Date.now()}`;
}

export function isOurs(name) {
  return typeof name === "string" && name.startsWith(RESOURCE_PREFIX);
}
