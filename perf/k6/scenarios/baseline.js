// Gentle steady load: ramps to at most 5 VUs, 3 minutes total, 1-3s think
// time between page visits. Sized for a 3-node/2-pod prod cluster — this is
// meant to look like a handful of people browsing, not a load test.
import { sleep } from "k6";
import { pages } from "../lib/endpoints.js";
import { buildThresholds } from "../lib/thresholds.js";
import { summaryOutputs } from "../lib/summary.js";

export const options = {
  scenarios: {
    baseline: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "30s", target: 5 },
        { duration: "2m", target: 5 },
        { duration: "30s", target: 0 },
      ],
    },
  },
  thresholds: buildThresholds(),
};

export default function () {
  const page = pages[Math.floor(Math.random() * pages.length)];
  page.run();
  sleep(1 + Math.random() * 2);
}

export function handleSummary(data) {
  return summaryOutputs(data, "baseline");
}
