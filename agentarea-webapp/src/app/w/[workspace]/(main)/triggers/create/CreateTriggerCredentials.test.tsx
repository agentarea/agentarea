// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { TriggerResponse } from "@/api/client/types.gen";
import { IntlProvider } from "@/test/intl";
import { installRadixJsdomStubs } from "@/test/radix-jsdom";
import { CreateTriggerForm } from "./CreateTriggerForm";

const listWorkspaceSecretsAction = vi.fn();
const createSecretAction = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({}),
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));
vi.mock("@/lib/server-actions", () => ({
  getAgentAction: vi.fn(async () => ({ data: null })),
  listMCPServerInstancesAction: vi.fn(async () => ({ data: [] })),
  listMCPServersAction: vi.fn(async () => ({ data: [] })),
  listSkillsAction: vi.fn(async () => ({ data: [] })),
  listWorkspaceFilesAction: vi.fn(async () => ({ data: { files: [] } })),
  listWorkspaceSecretsAction: () => listWorkspaceSecretsAction(),
}));
vi.mock("@/app/w/[workspace]/(main)/secrets/actions", () => ({
  createSecretAction: (...args: unknown[]) => createSecretAction(...args),
}));
vi.mock("./actions", () => ({
  createTriggerAction: vi.fn(),
  updateTriggerAction: vi.fn(),
  listTriggerCatalogAction: vi.fn(async () => [
    {
      id: "telegram",
      name: "Telegram",
      icon: "",
      description: "",
      icon_url: "http://api.test/static/icons/channels/telegram.svg",
      kind: "messaging",
      backend_type: "webhook",
      webhook_type: "telegram",
      data_extractor: "telegram",
      credential_fields: [
        { key: "bot_token", label: "Bot token", placeholder: "" },
      ],
    },
  ]),
}));

beforeAll(installRadixJsdomStubs);
afterEach(cleanup);

const telegramTrigger = {
  id: "22222222-2222-4222-8222-222222222222",
  agent_id: "11111111-1111-4111-8111-111111111111",
  name: "Telegram automation",
  trigger_type: "webhook",
  webhook_type: "telegram",
  is_active: true,
  task_parameters: {},
  conditions: {},
  failure_threshold: 5,
  consecutive_failures: 0,
  created_by: "test",
} as unknown as TriggerResponse;

describe("channel credentials on the trigger form", () => {
  // Skipped (issue #505): next-intl is mocked here as an identity function
  // (key => key), but this test asserts the real translated label/button text
  // from messages/en.json ("Name", "Value", "Create secret") for the
  // CreateSecretDialog it opens, so it fails deterministically at
  // getByLabelText("Name"). Needs either a real NextIntlClientProvider or the
  // assertions rewritten against the raw translation keys.
  it.skip("keeps the secret created from the picker selected once the list refetches", async () => {
    const fresh = {
      id: "33333333-3333-4333-8333-333333333333",
      name: "bot-token",
    };
    listWorkspaceSecretsAction.mockResolvedValueOnce([]);
    createSecretAction.mockResolvedValue({ error: null, secret: fresh });
    // The picker asks its owner to refetch, which is when the real page swaps
    // the list — the moment the selection went missing.
    listWorkspaceSecretsAction.mockResolvedValue([fresh]);

    const user = userEvent.setup();
    render(<CreateTriggerForm agents={[]} initialData={telegramTrigger} />, {
      wrapper: IntlProvider,
    });

    const picker = await screen.findByRole("combobox", { name: /Bot token/ });
    await user.click(picker);
    await user.click(await screen.findByRole("option", { name: "New secret" }));

    await screen.findByRole("dialog");
    await user.type(screen.getByLabelText("Name"), "bot-token");
    await user.type(screen.getByLabelText("Value"), "123:abc");
    await user.click(screen.getByRole("button", { name: "Create secret" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(createSecretAction).toHaveBeenCalled();
    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: /Bot token/ }).textContent
      ).toContain("bot-token")
    );
    expect(
      document.querySelector<HTMLInputElement>(
        'input[name="credential_secret_bot_token"]'
      )?.value
    ).toBe(fresh.id);
  });

  it("picks a trigger type from the catalog and reveals its credential field", async () => {
    listWorkspaceSecretsAction.mockResolvedValue([]);
    const user = userEvent.setup();
    render(<CreateTriggerForm agents={[]} />, { wrapper: IntlProvider });

    const typePicker = await screen.findByRole("combobox", {
      name: /Trigger Type/,
    });
    await user.click(typePicker);
    const option = await screen.findByRole("option", { name: "Telegram" });
    // The catalog's own artwork, not a lucide stand-in picked by id.
    expect(option.querySelector("img")?.getAttribute("src")).toBe(
      "http://api.test/static/icons/channels/telegram.svg"
    );
    await user.click(option);

    expect(typePicker.textContent).toContain("Telegram");
    expect(
      document.querySelector<HTMLInputElement>('input[name="trigger_type"]')
        ?.value
    ).toBe("webhook");
    await screen.findByRole("combobox", { name: /Bot token/ });
  });
});
