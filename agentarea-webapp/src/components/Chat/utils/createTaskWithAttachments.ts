import { uploadAttachments } from "./uploadAttachments";

interface CreateTaskWithAttachmentsOptions {
  files: readonly File[];
  onAccepted: () => void;
  request: (attachmentRefs: string[]) => Promise<Response>;
}

export type AcceptedTaskResponse = Response & {
  body: ReadableStream<Uint8Array>;
};

/** Keep the composer draft intact until uploads and task acceptance succeed. */
export async function createTaskWithAttachments({
  files,
  onAccepted,
  request,
}: CreateTaskWithAttachmentsOptions): Promise<AcceptedTaskResponse> {
  const attachmentRefs = await uploadAttachments(files);
  const response = await request(attachmentRefs);
  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(
      errorBody || `Task creation failed with status ${response.status}`
    );
  }
  if (!response.body) throw new Error("No response body");
  onAccepted();
  return response as AcceptedTaskResponse;
}
