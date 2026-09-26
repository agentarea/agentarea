// Page-level metrics. Per-endpoint numbers come for free from k6's built-in
// http_req_duration / http_reqs / http_req_failed, split by the `name` tag
// via the threshold submetrics in lib/thresholds.js — these two cover the
// thing the built-ins can't: how long a whole page's fetches took together.
import { Counter, Trend } from "k6/metrics";

export const pageLoadDuration = new Trend("page_load_duration", true);
export const pageVisits = new Counter("page_visits");
