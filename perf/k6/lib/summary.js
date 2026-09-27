// Turns the raw k6 summary into the markdown table the PR/report wants, plus
// a full JSON dump for anything the table leaves out. Pulls per-endpoint and
// per-page numbers out of the threshold submetrics lib/thresholds.js forces
// into existence — no separate aggregation pass needed.

function fmtMs(n) {
  return n === undefined || n === null || Number.isNaN(n) ? "-" : n.toFixed(1);
}

function fmtPct(n) {
  return n === undefined || n === null || Number.isNaN(n) ? "-" : `${(n * 100).toFixed(2)}%`;
}

function rowsFor(data, durationMetric, countMetric, tagName, extra) {
  const seen = new Set();
  const rows = [];
  const pattern = new RegExp(`^${durationMetric}\\{${tagName}:(.+)\\}$`);
  for (const key of Object.keys(data.metrics)) {
    const match = key.match(pattern);
    if (!match) continue;
    const label = match[1];
    if (seen.has(label)) continue;
    seen.add(label);
    const durValues = data.metrics[key].values;
    const count = data.metrics[`${countMetric}{${tagName}:${label}}`]?.values?.count ?? 0;
    rows.push(
      Object.assign(
        {
          label,
          count,
          p50: durValues.med,
          p95: durValues["p(95)"],
          max: durValues.max,
        },
        extra ? extra(data, label) : {}
      )
    );
  }
  return rows.sort((a, b) => a.label.localeCompare(b.label));
}

function failedThresholds(data) {
  const failed = [];
  for (const [metricName, metric] of Object.entries(data.metrics)) {
    if (!metric.thresholds) continue;
    for (const [expr, result] of Object.entries(metric.thresholds)) {
      if (!result.ok) failed.push(`${metricName}: ${expr}`);
    }
  }
  return failed;
}

function markdownReport(data, scenario) {
  const endpointRows = rowsFor(data, "http_req_duration", "http_reqs", "name", (d, label) => ({
    errorRate: d.metrics[`http_req_failed{name:${label}}`]?.values?.rate ?? 0,
  }));
  const pageRows = rowsFor(data, "page_load_duration", "page_visits", "page");

  const lines = [];
  lines.push(`# k6 ${scenario} results`);
  lines.push("");
  lines.push(`Run at: ${new Date().toISOString()}`);
  lines.push("");
  lines.push("## Per-endpoint latency (ms)");
  lines.push("");
  lines.push("| endpoint | count | p50 | p95 | max | error rate |");
  lines.push("|---|---|---|---|---|---|");
  for (const r of endpointRows) {
    lines.push(
      `| ${r.label} | ${r.count} | ${fmtMs(r.p50)} | ${fmtMs(r.p95)} | ${fmtMs(r.max)} | ${fmtPct(r.errorRate)} |`
    );
  }
  lines.push("");
  lines.push("## Per-page latency (ms)");
  lines.push("");
  lines.push("| page | visits | p50 | p95 | max |");
  lines.push("|---|---|---|---|---|");
  for (const r of pageRows) {
    lines.push(`| ${r.label} | ${r.count} | ${fmtMs(r.p50)} | ${fmtMs(r.p95)} | ${fmtMs(r.max)} |`);
  }
  lines.push("");
  lines.push(`Overall http_req_failed: ${fmtPct(data.metrics.http_req_failed?.values?.rate ?? 0)}`);
  lines.push("");

  const failed = failedThresholds(data);
  if (failed.length) {
    lines.push("## Failed thresholds");
    lines.push("");
    lines.push(
      "These encode a target latency/error budget, not a pass/fail gate for this suite " +
        "today — see the PR description for context on which are expected to fail."
    );
    lines.push("");
    for (const f of failed.sort()) lines.push(`- ${f}`);
  } else {
    lines.push("All thresholds passed.");
  }
  return lines.join("\n") + "\n";
}

export function summaryOutputs(data, scenario) {
  const md = markdownReport(data, scenario);
  const out = {
    stdout: md,
  };
  out[`results/${scenario}-report.md`] = md;
  out[`results/${scenario}-summary.json`] = JSON.stringify(data, null, 2);
  return out;
}
