// Gentle mixed load: journeys weighted like real usage (browse dominates),
// ramps to at most 5 VUs, ~5-8 minutes total. Meant to run nightly from an
// in-cluster CronJob (see perf-dashboards for the CronJob + Grafana side)
// against the dedicated perf-k6 workspace.
//
// task_run runs in its own scenario with its own shared-iterations executor
// so its real per-run LLM cost is capped at TASK_RUN_LIMIT total runs — never
// multiplied by the mixed scenario's VU count.
import { sleep } from "k6";
import {
  weightedPool,
  IS_PERF_WORKSPACE,
  runJanitor,
  taskRunJourney,
} from "../../lib/journeys/index.js";
import { buildJourneyThresholds } from "../../lib/journeys/thresholds.js";

const TASK_RUN_LIMIT = Number(__ENV.TASK_RUN_LIMIT || 3);

const scenarios = {
  mixed: {
    executor: "ramping-vus",
    exec: "mixed",
    startVUs: 0,
    stages: [
      { duration: "1m", target: 5 },
      { duration: "5m", target: 5 },
      { duration: "1m", target: 0 },
    ],
  },
};

if (IS_PERF_WORKSPACE && TASK_RUN_LIMIT > 0) {
  scenarios.task_run = {
    executor: "shared-iterations",
    exec: "taskRun",
    vus: 1,
    iterations: TASK_RUN_LIMIT,
    maxDuration: "10m",
    startTime: "10s", // let the janitor and first few mixed iterations settle first
  };
}

export const options = {
  scenarios,
  thresholds: buildJourneyThresholds(),
};

export function setup() {
  if (IS_PERF_WORKSPACE) {
    runJanitor();
  } else {
    console.log("nightly: WORKSPACE is not perf-k6 — read-only journeys only, write journeys skipped");
  }
}

const pool = weightedPool();

export function mixed() {
  const journey = pool[Math.floor(Math.random() * pool.length)];
  journey.run();
  sleep(1 + Math.random() * 2);
}

export function taskRun() {
  taskRunJourney.run();
}

export function teardown() {
  if (IS_PERF_WORKSPACE) {
    runJanitor();
  }
}
