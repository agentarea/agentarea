// Thin request wrappers so every call is tagged and checked the same way.
import http from "k6/http";
import { check } from "k6";
import { authHeaders } from "./config.js";

// Default k6 behavior only counts network errors as "failed" — a 404 or 500
// still shows as a successful HTTP transaction. Redefining success as exactly
// 200 makes http_req_failed (and its threshold) mean what the brief asks for.
http.setResponseCallback(http.expectedStatuses(200));

export function get(path, name, extraTags) {
  const res = http.get(path, {
    headers: authHeaders(),
    tags: Object.assign({ name }, extraTags),
  });
  check(res, { [`${name} -> 200`]: (r) => r.status === 200 });
  return res;
}

export function getPublic(path, name, extraTags) {
  const res = http.get(path, {
    tags: Object.assign({ name }, extraTags),
  });
  check(res, { [`${name} -> 200`]: (r) => r.status === 200 });
  return res;
}

export function batchGet(requests) {
  // requests: [{ path, name }]
  const reqs = requests.map((r) => ({
    method: "GET",
    url: r.path,
    params: { headers: authHeaders(), tags: { name: r.name } },
  }));
  const responses = http.batch(reqs);
  responses.forEach((res, i) => {
    check(res, { [`${requests[i].name} -> 200`]: (r) => r.status === 200 });
  });
  return responses;
}
