// Thin request wrappers so every call is tagged and checked the same way.
import http from "k6/http";
import { check } from "k6";
import { authHeaders } from "./config.js";

// Default k6 behavior only counts network errors as "failed" — a 404 or 500
// still shows as a successful HTTP transaction. Redefining success as one of
// this API's real 2xx codes makes http_req_failed (and its threshold) mean
// what the brief asks for: 200 for reads/updates, 201 for most creates, 204
// for no-content deletes. Callers still `check()` the exact code they expect
// per call — this only fixes the built-in failure metric.
http.setResponseCallback(http.expectedStatuses(200, 201, 204));

// `kind` (read/write) is set here, by method, not by call sites — it's what
// the journey-suite thresholds key on (see lib/journeys/thresholds.js), and
// deriving it from the verb means no journey can forget to tag it.
export function get(path, name, extraTags) {
  const res = http.get(path, {
    headers: authHeaders(),
    tags: Object.assign({ name, kind: "read" }, extraTags),
  });
  check(res, { [`${name} -> 200`]: (r) => r.status === 200 });
  return res;
}

export function getPublic(path, name, extraTags) {
  const res = http.get(path, {
    tags: Object.assign({ name, kind: "read" }, extraTags),
  });
  check(res, { [`${name} -> 200`]: (r) => r.status === 200 });
  return res;
}

export function batchGet(requests) {
  // requests: [{ path, name, tags? }] — tags merges over { name, kind }, same as get().
  const reqs = requests.map((r) => ({
    method: "GET",
    url: r.path,
    params: {
      headers: authHeaders(),
      tags: Object.assign({ name: r.name, kind: "read" }, r.tags),
    },
  }));
  const responses = http.batch(reqs);
  responses.forEach((res, i) => {
    check(res, { [`${requests[i].name} -> 200`]: (r) => r.status === 200 });
  });
  return responses;
}

// Write helpers for journeys. These don't check() a status themselves —
// expected codes vary per call (200/201/204) — the caller checks and decides
// whether to keep going.
function jsonHeaders() {
  return Object.assign({ "Content-Type": "application/json" }, authHeaders());
}

export function postJson(path, body, name, extraTags) {
  return http.post(path, JSON.stringify(body), {
    headers: jsonHeaders(),
    tags: Object.assign({ name, kind: "write" }, extraTags),
  });
}

export function patchJson(path, body, name, extraTags) {
  return http.patch(path, JSON.stringify(body), {
    headers: jsonHeaders(),
    tags: Object.assign({ name, kind: "write" }, extraTags),
  });
}

export function putJson(path, body, name, extraTags) {
  return http.put(path, JSON.stringify(body), {
    headers: jsonHeaders(),
    tags: Object.assign({ name, kind: "write" }, extraTags),
  });
}

export function del(path, name, extraTags) {
  return http.del(path, null, {
    headers: authHeaders(),
    tags: Object.assign({ name, kind: "write" }, extraTags),
  });
}

// A GET whose own timeout is tunable — the SSE events/stream call can run for
// as long as the task takes, well past k6's default request timeout. Tagged
// "read" like any other GET, even though it's really "wait for a write's
// side effect to finish" — task_accepted/task_first_event/task_completed
// (lib/journeys/metrics.js) carry the meaningful timing for this one, not
// http_req_duration{kind}.
export function getWithTimeout(path, name, timeout, extraTags) {
  return http.get(path, {
    headers: authHeaders(),
    timeout,
    tags: Object.assign({ name, kind: "read" }, extraTags),
  });
}
