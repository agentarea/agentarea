// SLO targets, not today's reality — expect failures until things catch up.
// Category-level (kind: read/write), not per-endpoint: the journey suite's
// real reporting surface is Grafana over the Prometheus-remote-write output
// (see README "Metric contract"), not a local markdown table, so there's no
// need to force per-tag submetrics into existence here the way the
// browse-only suite's lib/thresholds.js does.
export function buildJourneyThresholds() {
  return {
    "http_req_duration{kind:read}": ["p(95)<500"],
    "http_req_duration{kind:write}": ["p(95)<1000"],
    page_load: ["p(95)<1000"],
    task_accepted: ["p(95)<1000"],
    task_first_event: ["p(95)<5000"],
    http_req_failed: ["rate<0.01"],
    checks: ["rate>0.99"],
  };
}
