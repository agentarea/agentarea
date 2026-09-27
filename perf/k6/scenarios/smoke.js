// 1 VU, 1 iteration, every page once. Correctness + single-request latency —
// run this before baseline to catch a broken endpoint (wrong path, auth
// failure) without spending baseline's 3 minutes on it.
import { pages } from "../lib/endpoints.js";
import { buildThresholds } from "../lib/thresholds.js";
import { summaryOutputs } from "../lib/summary.js";

export const options = {
  scenarios: {
    smoke: {
      executor: "shared-iterations",
      vus: 1,
      iterations: 1,
      maxDuration: "2m",
    },
  },
  thresholds: buildThresholds(),
};

export default function () {
  for (const page of pages) {
    page.run();
  }
}

export function handleSummary(data) {
  return summaryOutputs(data, "smoke");
}
