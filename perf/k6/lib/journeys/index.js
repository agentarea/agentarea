// Single place that assembles the journey pools each scenario reads from,
// so smoke/nightly/stress never drift on which journeys exist.
//
// task_run is deliberately NOT in any pool here: it has a real per-run LLM
// cost, so it must never be picked at random or multiplied by VU count. Each
// scenario gives it its own dedicated shared-iterations executor instead
// (see scenarios/journeys/*.js) and calls taskRunJourney.run() directly.
import { pages as browsePages } from "./browse.js";
import { authJourney } from "./auth.js";
import { agentLifecycle } from "./agent_lifecycle.js";
import { connectionLifecycle } from "./connection_lifecycle.js";
import { triggerLifecycle } from "./trigger_lifecycle.js";
import { skillLifecycle } from "./skill_lifecycle.js";
import { IS_PERF_WORKSPACE } from "./guard.js";

export { taskRunJourney } from "./task_run.js";
export { runJanitor } from "./janitor.js";
export { IS_PERF_WORKSPACE, PERF_WORKSPACE } from "./guard.js";

export const browseJourneys = browsePages;
export const writeJourneys = [agentLifecycle, connectionLifecycle, triggerLifecycle, skillLifecycle];

// Every read-only journey, plus the write ones if (and only if) this run is
// pointed at the perf-k6 workspace. Used by smoke: one pass through all of it.
export function allJourneysOnce() {
  const list = [...browseJourneys, authJourney];
  if (IS_PERF_WORKSPACE) list.push(...writeJourneys);
  return list;
}

// A weighted pool for nightly's random pick: browse dominates (that's most of
// real traffic), auth journeys occasionally, lifecycle journeys rarer still —
// each write journey already does 3-6 requests per pick, so a low weight
// still exercises it plenty over an 5-8 minute run.
export function weightedPool() {
  const pool = [];
  for (const page of browseJourneys) {
    pool.push(page, page, page); // 3x weight: the bulk of a real session
  }
  pool.push(authJourney);
  if (IS_PERF_WORKSPACE) {
    pool.push(...writeJourneys);
  }
  return pool;
}
