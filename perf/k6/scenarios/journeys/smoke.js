// 1 VU, 1 iteration, every journey once — CI-safe against a local stack (a
// local stack's WORKSPACE just needs to literally be "perf-k6" for the write
// journeys to run; against any other workspace they're skipped, not failed).
import { allJourneysOnce, IS_PERF_WORKSPACE, runJanitor, taskRunJourney } from "../../lib/journeys/index.js";
import { buildJourneyThresholds } from "../../lib/journeys/thresholds.js";

export const options = {
  scenarios: {
    smoke: {
      executor: "shared-iterations",
      vus: 1,
      iterations: 1,
      maxDuration: "5m",
    },
  },
  thresholds: buildJourneyThresholds(),
};

export function setup() {
  if (IS_PERF_WORKSPACE) {
    runJanitor();
  } else {
    console.log("smoke: WORKSPACE is not perf-k6 — read-only journeys only, write journeys skipped");
  }
}

export default function () {
  for (const journey of allJourneysOnce()) {
    journey.run();
  }
  // Safe to call inline here (not via a separate executor) because smoke is
  // already vus:1/iterations:1 — there is no VU count to multiply it by.
  if (IS_PERF_WORKSPACE) {
    taskRunJourney.run();
  }
}

export function teardown() {
  if (IS_PERF_WORKSPACE) {
    runJanitor();
  }
}
