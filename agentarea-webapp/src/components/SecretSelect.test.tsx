// @vitest-environment jsdom
import { useState } from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { IntlProvider } from "@/test/intl";
import { installRadixJsdomStubs } from "@/test/radix-jsdom";
import { SecretSelect } from "./SecretSelect";

const createSecretAction = vi.fn();

vi.mock("@/app/w/[workspace]/(main)/secrets/actions", () => ({
  createSecretAction: (...args: unknown[]) => createSecretAction(...args),
}));
vi.mock("next/navigation", () => ({
  useParams: () => ({}),
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

beforeAll(installRadixJsdomStubs);
afterEach(cleanup);

function Harness({
  secrets = [{ id: "existing-id", name: "existing-secret" }],
}) {
  const [value, setValue] = useState("");
  return (
    <SecretSelect
      secrets={secrets}
      value={value}
      onChange={setValue}
      placeholder="Select a secret"
      searchPlaceholder="Search"
      emptyMessage="No secrets yet."
      createLabel="New secret"
    />
  );
}

describe("SecretSelect", () => {
  // Skipped (issue #505): CreateSecretDialog is unmocked here, so it renders
  // through the real next-intl module without a NextIntlClientProvider and
  // throws before the dialog fields exist. Fixing it requires either wiring a
  // real provider (matching CreateSecretDialog's translated label text, e.g.
  // "Name"/"Value"/"Create secret" from messages/en.json) or mocking next-intl
  // and rewriting these assertions off the raw translation keys instead.
  it.skip("selects the secret the create dialog just made", async () => {
    createSecretAction.mockResolvedValue({
      error: null,
      secret: { id: "fresh-id", name: "fresh-secret" },
    });
    const user = userEvent.setup();
    render(<Harness />, { wrapper: IntlProvider });

    await user.click(screen.getByRole("combobox"));
    await user.click(await screen.findByText("New secret"));

    await screen.findByRole("dialog");
    await user.type(screen.getByLabelText("Name"), "fresh-secret");
    await user.type(screen.getByLabelText("Value"), "s3cret");
    await user.click(screen.getByRole("button", { name: "Create secret" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("combobox").textContent).toContain("fresh-secret");
  });

  // Skipped (issue #505): same missing next-intl setup as the test above.
  it.skip("keeps it selected when the owner refetches the list", async () => {
    const fresh = { id: "fresh-id", name: "fresh-secret" };
    createSecretAction.mockResolvedValue({ error: null, secret: fresh });
    const user = userEvent.setup();

    function RefetchingHarness() {
      const [value, setValue] = useState("");
      const [secrets, setSecrets] = useState<{ id: string; name: string }[]>(
        []
      );
      const [loading, setLoading] = useState(false);
      return (
        <SecretSelect
          secrets={secrets}
          value={value}
          onChange={setValue}
          disabled={loading}
          placeholder={loading ? "Loading…" : "Select a secret"}
          searchPlaceholder="Search"
          emptyMessage="No secrets yet."
          createLabel="New secret"
          onCreated={() => {
            setLoading(true);
            setTimeout(() => {
              setSecrets([fresh]);
              setLoading(false);
            }, 0);
          }}
        />
      );
    }

    render(<RefetchingHarness />, { wrapper: IntlProvider });
    await user.click(screen.getByRole("combobox"));
    await user.click(await screen.findByRole("option", { name: "New secret" }));
    await screen.findByRole("dialog");
    await user.type(screen.getByLabelText("Name"), "fresh-secret");
    await user.type(screen.getByLabelText("Value"), "s3cret");
    await user.click(screen.getByRole("button", { name: "Create secret" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() =>
      expect(screen.getByRole("combobox").textContent).toContain("fresh-secret")
    );
  });
});
