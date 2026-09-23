import { describe, expect, it, vi } from "vitest";
import { deliverTaskMessage } from "./deliverTaskMessage";

function actions() {
  return {
    createFollowupTask: vi.fn(async () => "new-task"),
    queueMessage: vi.fn(async () => ({})),
    submitInput: vi.fn(async () => ({})),
  };
}

describe("deliverTaskMessage", () => {
  it("sends attachments through task creation instead of queue or input", async () => {
    const taskActions = actions();
    const file = new File(["data"], "data.csv", { type: "text/csv" });

    const result = await deliverTaskMessage({
      actions: taskActions,
      files: [file],
      message: "Use this",
      pendingInputId: "input-1",
      queueOnCurrentTask: true,
    });

    expect(result).toEqual({ route: "followup", taskId: "new-task" });
    expect(taskActions.createFollowupTask).toHaveBeenCalledWith("Use this", [
      file,
    ]);
    expect(taskActions.queueMessage).not.toHaveBeenCalled();
    expect(taskActions.submitInput).not.toHaveBeenCalled();
  });

  it("preserves text-only input and queue delivery", async () => {
    const inputActions = actions();
    await deliverTaskMessage({
      actions: inputActions,
      files: [],
      message: "approve",
      pendingInputId: "input-1",
      queueOnCurrentTask: true,
    });
    expect(inputActions.submitInput).toHaveBeenCalledWith(
      "input-1",
      { answer: "approve" },
      {}
    );
    expect(inputActions.createFollowupTask).not.toHaveBeenCalled();

    const queueActions = actions();
    await deliverTaskMessage({
      actions: queueActions,
      files: [],
      message: "continue",
      queueOnCurrentTask: true,
    });
    expect(queueActions.queueMessage).toHaveBeenCalledWith("continue");
    expect(queueActions.createFollowupTask).not.toHaveBeenCalled();
  });
});
