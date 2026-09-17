/** Work out how to show a file from what it actually contains.
 *
 * Extensions are not evidence. Neither, on their own, are the types the
 * servers declare: the sandbox derives them with Python's `mimetypes`, which
 * has nothing at all for .md, .yaml, .toml, .go or .tsx, and calls .ts a video
 * stream. A list of extensions in the viewer would only be a second guess laid
 * over the first, so the viewer reads the opening bytes instead. */

export type MediaKind = "image" | "video" | "audio" | "pdf";

/** The media family a declared content type names, if it names one at all. */
export function mediaKind(
  contentType: string | null | undefined
): MediaKind | null {
  const type = (contentType ?? "").split(";")[0].trim().toLowerCase();
  if (type.startsWith("image/")) return "image";
  if (type.startsWith("video/")) return "video";
  if (type.startsWith("audio/")) return "audio";
  if (type === "application/pdf") return "pdf";
  return null;
}

/** Whether a file's opening bytes read as text.
 *
 * A NUL rules it out — it is valid UTF-8 but no editor writes one — and so
 * does any invalid sequence. The chunk may stop mid-character, which is an
 * artefact of where the read ended rather than a sign of binary content, so
 * decoding is streaming and a truncated tail is allowed. */
export function looksTextual(head: Uint8Array): boolean {
  if (head.includes(0)) return false;
  try {
    new TextDecoder("utf-8", { fatal: true }).decode(head, { stream: true });
    return true;
  } catch {
    return false;
  }
}
