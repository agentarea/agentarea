// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TaskConversation } from "./TaskConversation";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  refresh: vi.fn(),
  taskEvents: {
    parts: [],
    timeline: [],
    executionStatus: "running",
    isInteractionClosed: () => false,
    status: "idle",
    pendingForm: null,
    terminalMessage: null,
    completedRuns: [],
    loading: true,
    error: null as string | null,
    refresh: vi.fn(),
  },
}));

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({}),
  useRouter: () => ({ push: mocks.push, refresh: mocks.refresh }),
}));

vi.mock("@/lib/events/useTaskEvents", () => ({
  useTaskEvents: () => mocks.taskEvents,
}));

vi.mock("@/components/Chat/hooks/useA2UIActions", () => ({
  useA2UIActions: () => ({ dispatchAction: vi.fn() }),
}));

vi.mock("@/hooks/use-attachable-resources", () => ({
  useAttachableResources: vi.fn(),
}));

vi.mock("@/hooks/useTaskActions", () => ({
  useTaskActions: () => ({
    cancel: vi.fn(),
    createFollowupTask: vi.fn(),
    queueMessage: vi.fn(),
    resolveEscalation: vi.fn(),
    submitInput: vi.fn(),
  }),
}));

vi.mock("@/components/Chat/hooks/useScrollManagement", () => ({
  useScrollManagement: () => ({
    messagesContainerRef: { current: null },
    messagesEndRef: { current: null },
    handleScroll: vi.fn(),
  }),
}));

const task = {
  id: "task-1",
  agent_id: "agent-1",
  agent_name: "Agent",
  status: "running",
};

function selectFile(container: HTMLElement) {
  const file = new File(["draft"], "draft.txt", { type: "text/plain" });
  const input = container.querySelector('input[type="file"]');
  if (!(input instanceof HTMLInputElement))
    throw new Error("file input missing");
  fireEvent.change(input, { target: { files: [file] } });
}

describe("TaskConversation history lifecycle", () => {
  afterEach(cleanup);

  beforeEach(() => {
    mocks.taskEvents.parts = [];
    mocks.taskEvents.status = "idle";
    mocks.taskEvents.pendingForm = null;
    mocks.taskEvents.terminalMessage = null;
    mocks.taskEvents.completedRuns = [];
    mocks.taskEvents.loading = true;
    mocks.taskEvents.error = null;
    mocks.taskEvents.refresh.mockReset();
  });

  it("keeps the composer draft and files mounted from loading to loaded", () => {
    const view = render(<TaskConversation task={task} />);
    const textarea = screen.getByPlaceholderText("Message Agent...");
    const send = screen.getByRole("button", { name: "Send message" });

    expect((textarea as HTMLTextAreaElement).disabled).toBe(false);
    expect((send as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(textarea, { target: { value: "Continue with this" } });
    selectFile(view.container);
    expect(screen.getByText("draft.txt")).toBeTruthy();

    mocks.taskEvents.loading = false;
    view.rerender(<TaskConversation task={task} />);

    expect(screen.getByDisplayValue("Continue with this")).toBe(textarea);
    expect(screen.getByText("draft.txt")).toBeTruthy();
    expect((send as HTMLButtonElement).disabled).toBe(false);
  });

  it("keeps drafting available on history error while submission stays disabled", () => {
    const view = render(<TaskConversation task={task} />);
    const textarea = screen.getByPlaceholderText("Message Agent...");
    fireEvent.change(textarea, { target: { value: "Do not lose this" } });
    selectFile(view.container);

    mocks.taskEvents.loading = false;
    mocks.taskEvents.error = "History could not be loaded";
    view.rerender(<TaskConversation task={task} />);

    expect(
      (screen.getByDisplayValue("Do not lose this") as HTMLTextAreaElement)
        .disabled
    ).toBe(false);
    expect(screen.getByText("draft.txt")).toBeTruthy();
    expect(
      (
        screen.getByRole("button", {
          name: "Send message",
        }) as HTMLButtonElement
      ).disabled
    ).toBe(true);
    expect(
      screen.getByText(
        "Conversation history is unavailable. Retry loading before sending."
      )
    ).toBeTruthy();
  });
});
