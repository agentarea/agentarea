import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { CronScheduler } from "./CronScheduler";

vi.mock("@/components/ui/select", () => ({
  Select: ({ value, children }: { value: string; children: React.ReactNode }) => (
    <select value={value} onChange={() => {}}>{children}</select>
  ),
  SelectContent: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  SelectItem: ({ value, children }: { value: string; children: React.ReactNode }) => (
    <option value={value}>{children}</option>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
}));

// Vitest's node renderer uses the classic JSX transform for this Next.js app.
beforeAll(() => vi.stubGlobal("React", React));
afterAll(() => vi.unstubAllGlobals());

function renderSchedule(expression: string) {
  return renderToStaticMarkup(
    <CronScheduler name="cron_expression" defaultValue={expression} />
  );
}

describe("CronScheduler existing schedules", () => {
  it.each([
    "0 9 * 1 *",
    "*/5 * * 1 *",
    "0 */2 * 1 *",
    "0 9 15 1 *",
    "0 9 * 1 1",
    "0,30 9 * * *",
    "0 9-17 * * *",
    "0 9 * * 1-5",
    "0 9 1,15 * *",
    "*/7 * * * *",
    "0 */5 * * *",
    "0 9 * * 7",
    "0 9 15 * 1",
    "0 0 9 * * *",
  ])("preserves %s in Custom instead of changing its schedule", (expression) => {
    const markup = renderSchedule(expression);

    expect(markup).toContain(
      `<input type="hidden" name="cron_expression" value="${expression}"/>`
    );
    expect(markup).toContain(`Custom: ${expression}`);
    expect(markup).toContain('id="cron_custom_expression"');
  });

  it.each([
    ["* * * * *", "Runs every minute"],
    ["*/5 * * * *", "Runs every 5 minutes"],
    ["7 * * * *", "Runs every hour at minute 7"],
    ["7 */2 * * *", "Runs every 2 hours at minute 7"],
    ["7 9 * * *", "Runs daily at 09:07"],
    ["7 9 * * 1", "Runs every Monday at 09:07"],
    ["7 9 15 * *", "Runs on the 15th of every month at 09:07"],
  ])("round trips supported preset %s", (expression, description) => {
    const markup = renderSchedule(expression);

    expect(markup).toContain(
      `<input type="hidden" name="cron_expression" value="${expression}"/>`
    );
    expect(markup).toContain(description);
    expect(markup).not.toContain('id="cron_custom_expression"');
  });

  it.each(["7 * * * *", "7 9 * * *", "7 9 * * 1", "7 9 15 * *"])(
    "offers all 60 minutes and displays minute 7 for %s",
    (expression) => {
      const markup = renderSchedule(expression);
      const selects = markup.match(/<select>[\s\S]*?<\/select>/g) ?? [];
      const minuteSelect = selects.find((select) => select.includes('value="59"'));

      expect(minuteSelect).toBeDefined();
      expect(minuteSelect?.match(/<option /g)).toHaveLength(60);
      expect(minuteSelect).toContain('<option value="7" selected="">');
    }
  );
});
