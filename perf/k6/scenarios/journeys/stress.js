// Heavier mixed load, for local/staging only. Double-gated: needs
// ALLOW_STRESS=1, AND refuses outright when AGENTAREA_API_URL is the real
// prod host — unlike the rest of this suite, that check is NOT just the
// workspace guard, because stress-level volume against prod is the one
// mistake this suite should make structurally impossible, not just
// discouraged.
import { sleep } from "k6";
import { BASE_URL } from "../../lib/config.js";
import { weightedPool, IS_PERF_WORKSPACE, runJanitor } from "../../lib/journeys/index.js";
import { buildJourneyThresholds } from "../../lib/journeys/thresholds.js";

const PROD_HOSTS = ["api.agentarea.ru"];

if (__ENV.ALLOW_STRESS !== "1") {
  throw new Error(
    "stress.js is disabled by default: it ramps well past nightly's 5 VUs and must " +
      "never run against production without an explicit operator decision. Set " +
      "ALLOW_STRESS=1 to run it — against a non-prod target only."
  );
}

if (PROD_HOSTS.some((host) => BASE_URL.includes(host))) {
  throw new Error(
    `stress.js refuses to run against ${BASE_URL} — this is prod. Point AGENTAREA_API_URL ` +
      "at a staging or local stack instead. This check does not have an override."
  );
}

export const options = {
  scenarios: {
    stress: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "1m", target: 20 },
        { duration: "3m", target: 50 },
        { duration: "1m", target: 0 },
      ],
    },
  },
  thresholds: buildJourneyThresholds(),
};

export function setup() {
  if (IS_PERF_WORKSPACE) runJanitor();
}

const pool = weightedPool();

export default function () {
  const journey = pool[Math.floor(Math.random() * pool.length)];
  journey.run();
  sleep(0.5 + Math.random());
}

export function teardown() {
  if (IS_PERF_WORKSPACE) runJanitor();
}
