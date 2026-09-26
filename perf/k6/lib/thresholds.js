// Threshold expressions do double duty in k6: besides pass/fail, each
// `{tag:value}` filter forces k6 to keep a separate submetric for that tag,
// which is what makes the per-endpoint and per-page breakdown in the summary
// report possible at all (see lib/summary.js). So every name/page below gets
// a threshold even where the number itself is a placeholder.
import { NAMES, pages } from "./endpoints.js";

function endpointThresholds() {
  const t = {};
  for (const name of Object.values(NAMES)) {
    const isHealth = name === NAMES.HEALTH;
    t[`http_req_duration{name:${name}}`] = [isHealth ? "p(95)<150" : "p(95)<500"];
    t[`http_req_failed{name:${name}}`] = ["rate<0.01"];
    // count>=0 always holds; it exists only to force the http_reqs submetric.
    t[`http_reqs{name:${name}}`] = ["count>=0"];
  }
  return t;
}

function pageThresholds() {
  const t = {};
  for (const page of pages) {
    t[`page_load_duration{page:${page.name}}`] = ["p(95)<1000"];
    t[`page_visits{page:${page.name}}`] = ["count>=0"];
  }
  return t;
}

export function buildThresholds() {
  return Object.assign(
    { http_req_failed: ["rate<0.01"] },
    endpointThresholds(),
    pageThresholds()
  );
}
