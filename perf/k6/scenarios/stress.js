// Heavier load, for local/staging only. Ramps well past baseline's 5 VUs, so
// it is gated behind an explicit opt-in and must never be pointed at prod:
//   ALLOW_STRESS=1 k6 run scenarios/stress.js
import { sleep } from "k6";
import { pages } from "../lib/endpoints.js";
import { buildThresholds } from "../lib/thresholds.js";
import { summaryOutputs } from "../lib/summary.js";

if (__ENV.ALLOW_STRESS !== "1") {
  throw new Error(
    "stress.js is disabled by default: it ramps to 50 VUs, well past what the baseline " +
      "considers gentle, and must never run against production without an explicit " +
      "operator decision. Set ALLOW_STRESS=1 to run it — against a non-prod target only."
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
  thresholds: buildThresholds(),
};

export default function () {
  const page = pages[Math.floor(Math.random() * pages.length)];
  page.run();
  sleep(0.5 + Math.random());
}

export function handleSummary(data) {
  return summaryOutputs(data, "stress");
}
