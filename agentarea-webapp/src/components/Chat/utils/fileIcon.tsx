import React from "react";
import {
  File,
  FileArchive,
  FileCode,
  FileImage,
  FileJson,
  FileSpreadsheet,
  FileText,
} from "lucide-react";
import { cn } from "@/lib/utils";

type IconType = React.ComponentType<{ className?: string }>;

interface FileMeta {
  Icon: IconType;
  /** Tailwind text color for the icon */
  className: string;
}

// extension (without dot) → icon + color
const EXT_META: Record<string, FileMeta> = {};
const register = (exts: string[], meta: FileMeta) => {
  for (const e of exts) EXT_META[e] = meta;
};

register(["csv", "tsv", "xls", "xlsx", "ods", "numbers"], {
  Icon: FileSpreadsheet,
  className: "text-green-600 dark:text-green-500",
});
register(["doc", "docx", "rtf", "odt", "pages"], {
  Icon: FileText,
  className: "text-blue-600 dark:text-blue-400",
});
register(["pdf"], { Icon: FileText, className: "text-red-600 dark:text-red-400" });
register(["json"], { Icon: FileJson, className: "text-amber-600 dark:text-amber-400" });
register(
  ["yaml", "yml", "xml", "toml", "ini", "env", "js", "ts", "tsx", "jsx", "py", "go", "rs", "rb", "java", "c", "cpp", "sh", "sql", "html", "css"],
  { Icon: FileCode, className: "text-sky-600 dark:text-sky-400" }
);
register(["png", "jpg", "jpeg", "gif", "svg", "webp", "bmp", "ico"], {
  Icon: FileImage,
  className: "text-sky-600 dark:text-sky-400",
});
register(["zip", "tar", "gz", "tgz", "rar", "7z"], {
  Icon: FileArchive,
  className: "text-zinc-500 dark:text-zinc-400",
});
register(["txt", "md", "log"], {
  Icon: FileText,
  className: "text-zinc-500 dark:text-zinc-400",
});

const KNOWN_EXTS = new Set(Object.keys(EXT_META));

/** Extract a trailing extension (lowercased) from a filename/path token. */
export function fileExtension(name: string): string | null {
  const clean = name.trim().split(/[?#]/)[0];
  const base = clean.split(/[\\/]/).pop() || clean;
  const m = base.match(/\.([a-z0-9]{1,8})$/i);
  return m ? m[1].toLowerCase() : null;
}

/** True when the token looks like a file with a recognized extension. */
export function isFileLike(name?: string | null): boolean {
  if (!name) return false;
  const ext = fileExtension(name);
  return !!ext && KNOWN_EXTS.has(ext);
}

export function getFileMeta(name: string): FileMeta {
  const ext = fileExtension(name);
  return (ext && EXT_META[ext]) || { Icon: File, className: "text-zinc-500" };
}

/** Just the basename for display. */
export function fileBasename(name: string): string {
  const clean = name.trim().split(/[?#]/)[0];
  return clean.split(/[\\/]/).pop() || clean;
}

/** A file chip: type icon + (optionally linked) filename. */
export const FileChip: React.FC<{
  name: string;
  href?: string;
  className?: string;
}> = ({ name, href, className }) => {
  const { Icon, className: iconColor } = getFileMeta(name);
  const label = fileBasename(name);
  const inner = (
    <>
      <Icon className={cn("h-4 w-4 shrink-0", iconColor)} />
      <span className="truncate">{label}</span>
    </>
  );

  if (href) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className={cn(
          "inline-flex max-w-full items-center gap-1.5 align-middle text-primary hover:underline",
          className
        )}
      >
        {inner}
      </a>
    );
  }

  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center gap-1.5 align-middle text-foreground",
        className
      )}
    >
      {inner}
    </span>
  );
};

export default FileChip;
