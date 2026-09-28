import type { PlannedUpload } from "@/api/client/types.gen";

/** The API's cap on entries in one upload plan. */
export const MAX_UPLOADS_PER_PLAN = 100;

export type FileDigest = { hex: string; base64: string };

/** SHA-256 of a file, as the hex the API plans with and the base64 the store checks. */
export async function digestFile(file: Blob): Promise<FileDigest> {
  const bytes = new Uint8Array(
    await crypto.subtle.digest("SHA-256", await file.arrayBuffer())
  );
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return {
    hex: Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join(
      ""
    ),
    base64: btoa(binary),
  };
}

/** Send a file's bytes straight to the object store with a presigned request. */
export async function putPlanned(
  planned: Pick<PlannedUpload, "path" | "upload_url" | "method" | "headers">,
  file: Blob
): Promise<void> {
  const { upload_url, method, headers } = planned;
  if (!upload_url || !method || !headers) {
    throw new Error(`No presigned upload was planned for ${planned.path}`);
  }
  const response = await fetch(upload_url, { method, headers, body: file });
  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(
      errorBody || `File upload failed with status ${response.status}`
    );
  }
}
