// Env wiring for every scenario. Fails at k6's init step (before any request
// fires) rather than partway through a run, so a missing token never shows up
// as a wall of 401s.

const rawUrl = __ENV.AGENTAREA_API_URL || "https://api.agentarea.ru";
export const BASE_URL = rawUrl.replace(/\/+$/, "");
export const WORKSPACE = __ENV.WORKSPACE;
export const TOKEN = __ENV.AGENTAREA_TOKEN;

if (!TOKEN) {
  throw new Error(
    "AGENTAREA_TOKEN is not set. `k6 run` forwards the whole process environment into " +
      "__ENV on its own, so exporting it is enough — no -e needed, and don't add one: " +
      "-e puts the value in argv, which any local `ps`/`pgrep -fl` shows in plaintext.\n" +
      "  set -a; . ~/.config/agentarea/ru.env; set +a\n" +
      "  make smoke   # or: k6 run scenarios/smoke.js"
  );
}

if (!WORKSPACE) {
  // No default on purpose: a wrong-but-plausible slug (the old default was
  // "user", since renamed to "jamakase54") silently hits someone else's
  // workspace instead of failing loudly.
  throw new Error(
    "WORKSPACE is not set. There is no default — pass the workspace slug explicitly:\n" +
      "  WORKSPACE=<slug> make smoke   # or: k6 run -e WORKSPACE=<slug> scenarios/smoke.js"
  );
}

export function authHeaders() {
  return { Authorization: `Bearer ${TOKEN}` };
}
