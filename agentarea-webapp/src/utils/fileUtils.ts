import {
  fileExtension,
  fileTypeLabel,
  getFileMeta,
} from "@/components/Chat/utils/fileIcon";

export interface FileTypeInfo {
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  type: string;
}

/** Attachment metadata backed by the same icon registry as chat file chips. */
export function getFileTypeInfo(file: File): FileTypeInfo {
  const meta = getFileMeta(file.name, file.type);
  return {
    icon: meta.Icon,
    color: meta.className,
    type: fileTypeLabel(file.name, file.type),
  };
}

export function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B";

  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));

  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

export function isImageFile(file: File): boolean {
  if (file.type.startsWith("image/")) return true;
  return [
    "jpg",
    "jpeg",
    "png",
    "gif",
    "bmp",
    "webp",
    "svg",
    "ico",
    "avif",
    "heic",
  ].includes(fileExtension(file.name) ?? "");
}

/**
 * Shorten file name to a maximum length while preserving the extension.
 * Adds three dots ... before the extension when truncated.
 */
export function shortenFileName(name: string, maxLength: number = 24): string {
  if (name.length <= maxLength) return name;
  const lastDotIndex = name.lastIndexOf(".");
  if (lastDotIndex <= 0 || lastDotIndex === name.length - 1) {
    return name.slice(0, Math.max(0, maxLength - 3)) + "...";
  }

  const base = name.slice(0, lastDotIndex);
  const ext = name.slice(lastDotIndex);
  const available = maxLength - ext.length - 3;
  if (available <= 0) {
    return name.slice(0, Math.max(0, maxLength - 3)) + "...";
  }

  const truncatedBase =
    base.length > available ? base.slice(0, available) + "..." : base;
  return truncatedBase + ext;
}
