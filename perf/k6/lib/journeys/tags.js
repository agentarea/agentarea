// One place that decides what a request's tags look like, so every journey
// tags requests the same way. `page` is only set for page-load requests
// (browse.js) — lifecycle/task/auth journeys pass no page.
export function tag(journey, step, page) {
  const t = { journey, step };
  if (page) t.page = page;
  return t;
}
