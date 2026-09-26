// Env wiring for every scenario. Fails at k6's init step (before any request
// fires) rather than partway through a run, so a missing token never shows up
// as a wall of 401s.

const rawUrl = __ENV.AGENTAREA_API_URL || "https://api.agentarea.ru";
export const BASE_URL = rawUrl.replace(/\/+$/, "");
export const WORKSPACE = __ENV.WORKSPACE || "user";
export const TOKEN = __ENV.AGENTAREA_TOKEN;

if (!TOKEN) {
  throw new Error(
    "AGENTAREA_TOKEN is not set. k6 does not read the process environment on its own — " +
      "every var must be forwarded with -e, even ones already exported in the shell:\n" +
      "  set -a; . ~/.config/agentarea/ru.env; set +a\n" +
      '  k6 run -e AGENTAREA_TOKEN="$AGENTAREA_TOKEN" -e AGENTAREA_API_URL="$AGENTAREA_API_URL" scenarios/smoke.js\n' +
      "or just `make smoke` / `make baseline`, which forwards them for you."
  );
}

export function authHeaders() {
  return { Authorization: `Bearer ${TOKEN}` };
}
