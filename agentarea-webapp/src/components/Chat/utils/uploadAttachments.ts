import { digestFile, putPlanned } from "@/lib/presigned-upload";
import { currentWorkspaceHeaders } from "@/lib/workspace-browser";

/** Upload a file to attachment staging and return its task-create reference. */
export async function uploadAttachment(file: File): Promise<string> {
  const digest = await digestFile(file);
  const contentType = file.type || "application/octet-stream";

  const presignResponse = await fetch("/api/files/upload-url", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...currentWorkspaceHeaders(),
    },
    body: JSON.stringify({
      filename: file.name,
      content_type: contentType,
      sha256: digest.hex,
      size: file.size,
    }),
  });
  if (!presignResponse.ok) {
    const errorBody = await presignResponse.text();
    throw new Error(
      errorBody || `Upload presign failed with status ${presignResponse.status}`
    );
  }

  const { ref, upload_url } = (await presignResponse.json()) as {
    ref: string;
    upload_url: string;
  };
  await putPlanned(
    {
      path: ref,
      upload_url,
      method: "PUT",
      headers: {
        "x-amz-checksum-sha256": digest.base64,
        "Content-Type": contentType,
      },
    },
    file
  );

  return ref;
}

export async function uploadAttachments(
  files: readonly File[]
): Promise<string[]> {
  const refs: string[] = [];
  for (const file of files) refs.push(await uploadAttachment(file));
  return refs;
}
