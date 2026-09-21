import { beforeEach, describe, expect, it, vi } from "vitest";
import { createFollowupAgentTask } from "@/components/Chat/utils/createFollowupAgentTask";
import { uploadAttachments } from "@/components/Chat/utils/uploadAttachments";

vi.mock("@/components/Chat/utils/uploadAttachments", () => ({
  uploadAttachments: vi.fn(),
}));

const mockedUploadAttachments = vi.mocked(uploadAttachments);

describe("createFollowupAgentTask", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockedUploadAttachments.mockReset();
  });

  it("uploads files and includes their refs in the task-create request", async () => {
    const file = new File(["data"], "data.csv", { type: "text/csv" });
    mockedUploadAttachments.mockResolvedValue(["staging/ref-1"]);
    const fetchMock = vi.fn(
      async () =>
        new Response('event: task_created\ndata: {"task_id":"task-2"}\n\n', {
          status: 200,
        })
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      createFollowupAgentTask("agent-1", "Analyze", [file])
    ).resolves.toBe("task-2");

    expect(mockedUploadAttachments).toHaveBeenCalledWith([file]);
    const [, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(JSON.parse(String(init?.body))).toMatchObject({
      attachments: ["staging/ref-1"],
      description: "Analyze",
    });
  });

  it("supports a files-only task description", async () => {
    mockedUploadAttachments.mockResolvedValue(["staging/ref-1"]);
    const fetchMock = vi.fn(
      async () =>
        new Response('event: task_created\ndata: {"task_id":"task-3"}\n\n', {
          status: 200,
        })
    );
    vi.stubGlobal("fetch", fetchMock);

    await createFollowupAgentTask("agent-1", "", []);

    const [, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(JSON.parse(String(init?.body)).description).toBe(
      "Use the attached files to complete the task."
    );
  });

  it("reads a split task-created record and stops an open event stream", async () => {
    mockedUploadAttachments.mockResolvedValue([]);
    const encoder = new TextEncoder();
    let cancelled = false;
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            'event: connected\ndata: {"message":"ready"}\n\nevent: task_created\ndata: {"task_'
          )
        );
        controller.enqueue(encoder.encode('id":"split-task"}\n\n'));
        // Deliberately remain open: navigation must not wait for task completion.
      },
      cancel() {
        cancelled = true;
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(stream, { status: 200 }))
    );

    await expect(createFollowupAgentTask("agent-1", "Analyze")).resolves.toBe(
      "split-task"
    );
    expect(cancelled).toBe(true);
  });
});
