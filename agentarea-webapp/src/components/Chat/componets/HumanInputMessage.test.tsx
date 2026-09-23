// @vitest-environment jsdom

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { HumanInputRequestData } from "../types";
import HumanInputMessage from "./HumanInputMessage";

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
afterEach(cleanup);

const request: HumanInputRequestData = {
  id: "input",
  input_request_id: "input",
  agent_id: "agent",
  timestamp: "",
  event_type: "input.request",
  question: "Select the project",
  questions: [
    { id: "project", question: "Project", type: "text", required: true },
  ],
};

describe("human input acknowledgement", () => {
  it("submits a numeric answer without converting it to a string", async () => {
    const submit = vi.fn().mockResolvedValue(undefined);
    render(
      <HumanInputMessage
        data={{
          ...request,
          questions: [
            { id: "count", question: "Count", type: "number", required: true },
          ],
          _onSubmit: submit,
        }}
      />
    );
    fireEvent.change(screen.getByRole("spinbutton", { name: "Count" }), {
      target: { value: "3" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() =>
      expect(submit).toHaveBeenCalledWith("input", { count: 3 }, {})
    );
  });

  it("does not claim the task resumed before a workflow response event", async () => {
    const view = render(
      <HumanInputMessage
        data={{ ...request, _onSubmit: vi.fn().mockResolvedValue(undefined) }}
      />
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Project" }), {
      target: { value: "Release" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Submit" })).toBeTruthy()
    );
    expect(screen.queryByText("Information provided")).toBeNull();
    view.rerender(
      <HumanInputMessage
        data={{ ...request, event_type: "input.response", resolved: true }}
      />
    );
    expect(screen.getByText("Information provided")).toBeTruthy();
  });

  it("retains the answer for retry when the server rejects submission", async () => {
    render(
      <HumanInputMessage
        data={{
          ...request,
          _onSubmit: vi.fn().mockRejectedValue(new Error("Request expired")),
        }}
      />
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Project" }), {
      target: { value: "Release" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByRole("alert");
    expect(screen.queryByText("Information provided")).toBeNull();
    expect(
      (screen.getByRole("textbox", { name: "Project" }) as HTMLInputElement)
        .value
    ).toBe("Release");
    expect(
      (screen.getByRole("button", { name: "Submit" }) as HTMLButtonElement)
        .disabled
    ).toBe(false);
  });
});
