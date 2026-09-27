// The metric contract. Names and tags here are load-bearing: perf-dashboards
// builds Grafana panels and alerts against the Prometheus series these
// produce under `-o experimental-prometheus-rw` (see README "Metric
// contract" for the exact resulting series names). Changing a metric name or
// a tag key here is a breaking change to that contract.
import { Counter, Trend } from "k6/metrics";

// A "page" is one or more requests that make up a single real page view (see
// browse.js) — this is the group-level latency, not any one request's.
export const pageLoad = new Trend("page_load", true);
export const pageVisits = new Counter("page_visits");

// The task-run journey's three checkpoints (see journeys/task_run.js):
// accepted = the POST /sync call returning a task at all;
// first_event = TTFB on the events/stream SSE call (the "connected" frame);
// completed = the events/stream call closing at a terminal event.
export const taskAccepted = new Trend("task_accepted", true);
export const taskFirstEvent = new Trend("task_first_event", true);
export const taskCompleted = new Trend("task_completed", true);
export const taskRuns = new Counter("task_runs");
