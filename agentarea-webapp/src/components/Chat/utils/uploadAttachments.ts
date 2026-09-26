import { currentWorkspaceHeaders } from "@/lib/workspace-browser";

function bufferToHex(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function bufferToBase64(buffer: ArrayBuffer): string {
  let binary = "";
  for (const byte of new Uint8Array(buffer)) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary);
}

/** Upload a file to attachment staging and return its task-create reference. */
export async function uploadAttachment(file: File): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    await file.arrayBuffer()
  );
  const sha256Hex = bufferToHex(digest);
  const sha256Base64 = bufferToBase64(digest);
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
      sha256: sha256Hex,
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
  const putResponse = await fetch(upload_url, {
    method: "PUT",
    headers: {
      "x-amz-checksum-sha256": sha256Base64,
      "Content-Type": contentType,
    },
    body: file,
  });
  if (!putResponse.ok) {
    const errorBody = await putResponse.text();
    throw new Error(
      errorBody || `File upload failed with status ${putResponse.status}`
    );
  }

  return ref;
}

export async function uploadAttachments(
  files: readonly File[]
): Promise<string[]> {
  const refs: string[] = [];
  for (const file of files) refs.push(await uploadAttachment(file));
  return refs;
}
