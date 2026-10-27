/** The windows the metrics tab reports on, as `?period=` carries them. */
export const METRICS_PERIODS = ["24h", "7d", "30d", "all"] as const;
export type MetricsPeriod = (typeof METRICS_PERIODS)[number];

export const DEFAULT_METRICS_PERIOD: MetricsPeriod = "24h";

const HOURS: Record<MetricsPeriod, number | undefined> = {
  "24h": 24,
  "7d": 7 * 24,
  "30d": 30 * 24,
  // No window: the API then counts the whole history, as the overview does.
  all: undefined,
};

/** `?period=` as given, or the default for anything it does not know. */
export function parseMetricsPeriod(raw: unknown): MetricsPeriod {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return (
    METRICS_PERIODS.find((period) => period === value) ?? DEFAULT_METRICS_PERIOD
  );
}

/** The `hours` the metrics endpoint takes for a period; none for all time. */
export function metricsPeriodHours(period: MetricsPeriod): number | undefined {
  return HOURS[period];
}
