import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import type { TriggerResponse } from "@/api/client/types.gen";
import { CreateTriggerForm } from "./CreateTriggerForm";

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));
vi.mock("@/lib/server-actions", () => ({
  listMCPServerInstancesAction: vi.fn(),
  listSkillsAction: vi.fn(),
  listWorkspaceFilesAction: vi.fn(),
}));
vi.mock("@/app/(main)/bundles/components/actions", () => ({
  listWorkspaceSecretsAction: vi.fn(),
}));
vi.mock("./actions", () => ({
  createTriggerAction: vi.fn(),
  updateTriggerAction: vi.fn(),
  listTriggerCatalogAction: vi.fn(),
}));
vi.mock("@/components/ui/select", () => ({
  Select: ({
    name,
    defaultValue,
    value,
    children,
  }: {
    name?: string;
    defaultValue?: string;
    value?: string;
    children: React.ReactNode;
  }) => (
    <select name={name} defaultValue={defaultValue ?? value}>
      {children}
    </select>
  ),
  SelectContent: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
  SelectItem: ({
    value,
    children,
  }: {
    value: string;
    children: React.ReactNode;
  }) => <option value={value}>{children}</option>,
  SelectTrigger: () => null,
  SelectValue: () => null,
}));

beforeAll(() => vi.stubGlobal("React", React));
afterAll(() => vi.unstubAllGlobals());

const trigger: TriggerResponse = {
  id: "22222222-2222-4222-8222-222222222222",
  agent_id: "11111111-1111-4111-8111-111111111111",
  name: "Existing automation",
  description: "Existing description",
  trigger_type: "cron",
  is_active: true,
  task_parameters: { text: "Existing task", budget: 2 },
  conditions: {},
  failure_threshold: 5,
  consecutive_failures: 0,
  created_by: "test",
  created_at: "2026-09-10T10:00:00Z",
  updated_at: "2026-09-10T10:00:00Z",
  cron_expression: "17 14 * * 1-5",
  timezone: "Asia/Kathmandu",
};

describe("existing automation form before the optional catalog loads", () => {
  it("renders saved cron, timezone, description and task from the API response", () => {
    const markup = renderToStaticMarkup(
      <CreateTriggerForm agents={[]} initialData={trigger} />
    );
    expect(markup).toContain('name="trigger_type" value="cron"');
    expect(markup).toContain('name="cron_expression" value="17 14 * * 1-5"');
    expect(markup).toContain('<option value="Asia/Kathmandu" selected="">');
    expect(markup).toMatch(
      /<textarea[^>]*name="description"[^>]*>Existing description<\/textarea>/
    );
    expect(markup).toMatch(
      /<textarea[^>]*id="task_text"[^>]*>Existing task<\/textarea>/
    );
    expect(markup).toContain("&quot;budget&quot;:2");
  });

  it("renders saved webhook methods and event filters without catalog metadata", () => {
    const markup = renderToStaticMarkup(
      <CreateTriggerForm
        agents={[]}
        initialData={{
          ...trigger,
          trigger_type: "webhook",
          webhook_type: "github",
          allowed_methods: ["PATCH"],
          event_types: ["push"],
        }}
      />
    );
    expect(markup).toContain('name="trigger_type" value="webhook"');
    expect(markup).toContain('name="webhook_type" value="github"');
    expect(markup).toContain('name="event_types" value="[&quot;push&quot;]"');
    expect(markup).toMatch(/aria-checked="true"[^>]*id="method_PATCH"/);
    expect(markup).not.toContain('name="cron_expression"');
  });
});
