// 1 VU, 1 iteration, every journey once — CI-safe against a local stack (a
// local stack's WORKSPACE just needs to literally be "perf-k6" for the write
// journeys to run; against any other workspace they're skipped, not failed).
import { check } from "k6";
import { allJourneysOnce, IS_PERF_WORKSPACE, runJanitor, taskRunJourney } from "../../lib/journeys/index.js";
import { ownedMcpSpec } from "../../lib/journeys/janitor.js";
import { KINDS, SUITE_TAG, isOurs, resourceName } from "../../lib/journeys/naming.js";
import { buildJourneyThresholds } from "../../lib/journeys/thresholds.js";

// Pure logic, no network: guards the janitor's ownership check against ever
// drifting loose enough to match a real catalog item (see naming.js's
// header comment for why this matters). Runs unconditionally, even
// read-only, because it costs nothing and a false positive here is exactly
// the kind of bug that only shows up once a matching catalog name exists.
function selfTestNaming() {
  for (const kind of KINDS) {
    const name = resourceName(kind);
    check(null, { [`isOurs() accepts our own "${kind}" name`]: () => isOurs(name) });
  }
  const adversarial = ["k6-mcp", "k6", "k6-grafana", "k6-grafana-mcp-server"];
  for (const name of adversarial) {
    check(null, { [`isOurs() rejects "${name}"`]: () => !isOurs(name) });
  }
  // A plausible catalog-shaped item: starts with our prefix, ends the way a
  // real catalog entry's own naming convention might, but is not the exact
  // suite-generated shape.
  check(null, {
    'isOurs() rejects a catalog-shaped "k6-something-42-1"': () => !isOurs("k6-something-42-1"),
  });

  // The name regex alone isn't the janitor's whole story for resources whose
  // list endpoint mixes in platform/catalog rows (MCP specs) — ownedMcpSpec()
  // also requires SUITE_TAG. A regex-shaped name with no tag must still be
  // rejected: a catalog sync could in principle produce a same-shaped name
  // by coincidence, and the tag is what actually proves this suite wrote it.
  const specName = resourceName("mcp-spec");
  check(null, {
    "ownedMcpSpec() rejects a regex-shaped name with no tag": () =>
      !ownedMcpSpec({ name: specName, tags: [] }),
    "ownedMcpSpec() accepts a regex-shaped name with SUITE_TAG": () =>
      ownedMcpSpec({ name: specName, tags: [SUITE_TAG] }),
  });
}

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
  selfTestNaming();
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
