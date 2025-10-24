import {
  Archive,
  Code,
  File,
  FileImage,
  FileSpreadsheet,
  FileText,
  Image,
  Music,
  Video,
} from "lucide-react";

export interface FileTypeInfo {
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  type: string;
}

export function getFileTypeInfo(file: File): FileTypeInfo {
  const extension = file.name.split(".").pop()?.toLowerCase() || "";

  // Image files
  if (
    ["jpg", "jpeg", "png", "gif", "bmp", "webp", "svg", "ico"].includes(
      extension
    )
  ) {
    return {
      icon: Image,
      color: "text-green-600",
      type: "Image",
    };
  }

  // Video files
  if (["mp4", "avi", "mov", "wmv", "flv", "webm", "mkv"].includes(extension)) {
    return {
      icon: Video,
      color: "text-purple-600",
      type: "Video",
    };
  }

  // Audio files
  if (["mp3", "wav", "flac", "aac", "ogg", "m4a"].includes(extension)) {
    return {
      icon: Music,
      color: "text-pink-600",
      type: "Audio",
    };
  }

  // Document files
  if (["pdf"].includes(extension)) {
    return {
      icon: FileImage,
      color: "text-red-600",
      type: "PDF",
    };
  }

  // Spreadsheet files
  if (["xlsx", "xls", "csv"].includes(extension)) {
    return {
      icon: FileSpreadsheet,
      color: "text-green-700",
      type: "Spreadsheet",
    };
  }

  // Code files
  if (
    [
      "js",
      "ts",
      "jsx",
      "tsx",
      "py",
      "java",
      "cpp",
      "c",
      "cs",
      "php",
      "rb",
      "go",
      "rs",
      "html",
      "css",
      "scss",
      "sass",
      "less",
      "xml",
      "json",
      "yaml",
      "yml",
    ].includes(extension)
  ) {
    return {
      icon: Code,
      color: "text-blue-600",
      type: "Code",
    };
  }

  // Archive files
  if (["zip", "rar", "7z", "tar", "gz", "bz2"].includes(extension)) {
    return {
      icon: Archive,
      color: "text-orange-600",
      type: "Archive",
    };
  }

  // Text files
  if (["txt", "md", "rtf", "doc", "docx"].includes(extension)) {
    return {
      icon: FileText,
      color: "text-gray-600",
      type: "Text",
    };
  }

  // Default file type
  return {
    icon: File,
    color: "text-gray-500",
    type: extension.toUpperCase() || "File",
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
  const extension = file.name.split(".").pop()?.toLowerCase() || "";
  return ["jpg", "jpeg", "png", "gif", "bmp", "webp", "svg", "ico"].includes(
    extension
  );
}

/**
 * Shorten file name to a maximum length while preserving the extension.
 * Adds three dots ... before the extension when truncated.
 */
export function shortenFileName(name: string, maxLength: number = 24): string {
  if (name.length <= maxLength) return name;
  const lastDotIndex = name.lastIndexOf(".");
  if (lastDotIndex <= 0 || lastDotIndex === name.length - 1) {
    // No extension or dot at the end — simple truncate
    return name.slice(0, Math.max(0, maxLength - 3)) + "...";
  }

  const base = name.slice(0, lastDotIndex);
  const ext = name.slice(lastDotIndex); // includes dot

  const available = maxLength - ext.length - 3; // space for ... + ext
  if (available <= 0) {
    // Extension itself is too long; fallback to generic truncate
    return name.slice(0, Math.max(0, maxLength - 3)) + "...";
  }

  const truncatedBase =
    base.length > available ? base.slice(0, available) + "..." : base;
  return truncatedBase + ext;
}
