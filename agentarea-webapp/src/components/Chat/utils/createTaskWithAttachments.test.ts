import { describe, expect, it, vi } from "vitest";
import { createTaskWithAttachments } from "./createTaskWithAttachments";

describe("createTaskWithAttachments", () => {
  it("does not commit an optimistic message when task creation fails", async () => {
    const onAccepted = vi.fn();

    await expect(
      createTaskWithAttachments({
        files: [],
        onAccepted,
        request: async () => new Response("task rejected", { status: 422 }),
      })
    ).rejects.toThrow("task rejected");

    expect(onAccepted).not.toHaveBeenCalled();
  });

  it("commits only after an accepted task has a response stream", async () => {
    const onAccepted = vi.fn();
    const response = await createTaskWithAttachments({
      files: [],
      onAccepted,
      request: async () => new Response("event: task.created", { status: 200 }),
    });

    expect(response.ok).toBe(true);
    expect(onAccepted).toHaveBeenCalledOnce();
  });
});
