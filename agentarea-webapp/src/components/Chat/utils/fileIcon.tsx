import React from "react";
import { cn } from "@/lib/utils";

export type FileIconType = React.ComponentType<{ className?: string }>;

export interface FileMeta {
  Icon: FileIconType;
  /** Kept for compatibility; vendored SVGs own their colors. */
  className: string;
  type: string;
}

const ASSET_ROOT = "/file-icons/material-icon-theme";

function assetIcon(asset: string): FileIconType {
  const FileAssetIcon: React.FC<{ className?: string }> = ({ className }) => (
    // Local pinned assets; LICENSE and SOURCE.md live beside the SVGs.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={`${ASSET_ROOT}/${asset}.svg`}
      alt=""
      aria-hidden
      width={20}
      height={20}
      className={cn("object-contain", className)}
    />
  );
  FileAssetIcon.displayName = `${asset}FileIcon`;
  return FileAssetIcon;
}

const ICONS = {
  python: assetIcon("python"),
  typescript: assetIcon("typescript"),
  javascript: assetIcon("javascript"),
  json: assetIcon("json"),
  markdown: assetIcon("markdown"),
  table: assetIcon("table"),
  pdf: assetIcon("pdf"),
  word: assetIcon("word"),
  powerpoint: assetIcon("powerpoint"),
  html: assetIcon("html"),
  css: assetIcon("css"),
  yaml: assetIcon("yaml"),
  toml: assetIcon("toml"),
  zip: assetIcon("zip"),
  image: assetIcon("image"),
  audio: assetIcon("audio"),
  video: assetIcon("video"),
  document: assetIcon("document"),
} as const;

const EXT_META: Record<string, FileMeta> = {};
const register = (exts: string[], Icon: FileIconType, type: string) => {
  for (const ext of exts) EXT_META[ext] = { Icon, className: "", type };
};

register(["py", "pyw", "pyi"], ICONS.python, "Python");
register(["ts", "tsx", "d.ts"], ICONS.typescript, "TypeScript");
register(["js", "jsx", "mjs", "cjs"], ICONS.javascript, "JavaScript");
register(["json", "jsonl", "geojson"], ICONS.json, "JSON");
register(["md", "mdx", "markdown"], ICONS.markdown, "Markdown");
register(["csv", "tsv", "xls", "xlsx", "ods", "numbers"], ICONS.table, "Spreadsheet");
register(["pdf"], ICONS.pdf, "PDF");
register(["doc", "docx", "rtf", "odt", "pages"], ICONS.word, "Document");
register(["ppt", "pptx", "odp", "key"], ICONS.powerpoint, "Presentation");
register(["html", "htm"], ICONS.html, "HTML");
register(["css", "scss", "sass", "less"], ICONS.css, "Stylesheet");
register(["yaml", "yml"], ICONS.yaml, "YAML");
register(["toml", "ini", "env", "properties"], ICONS.toml, "Configuration");
register(["zip", "tar", "gz", "tgz", "rar", "7z", "bz2", "xz"], ICONS.zip, "Archive");
register(["png", "jpg", "jpeg", "gif", "svg", "webp", "bmp", "ico", "avif", "heic"], ICONS.image, "Image");
register(["mp3", "wav", "flac", "aac", "ogg", "m4a", "opus"], ICONS.audio, "Audio");
register(["mp4", "avi", "mov", "wmv", "flv", "webm", "mkv", "m4v"], ICONS.video, "Video");

const MIME_META: Array<[RegExp, FileMeta]> = [
  [/^image\//, { Icon: ICONS.image, className: "", type: "Image" }],
  [/^audio\//, { Icon: ICONS.audio, className: "", type: "Audio" }],
  [/^video\//, { Icon: ICONS.video, className: "", type: "Video" }],
  [/pdf/i, { Icon: ICONS.pdf, className: "", type: "PDF" }],
  [/(spreadsheet|excel|csv)/i, { Icon: ICONS.table, className: "", type: "Spreadsheet" }],
  [/(word|document)/i, { Icon: ICONS.word, className: "", type: "Document" }],
  [/(presentation|powerpoint)/i, { Icon: ICONS.powerpoint, className: "", type: "Presentation" }],
  [/(zip|tar|compressed|archive)/i, { Icon: ICONS.zip, className: "", type: "Archive" }],
];

const FALLBACK_META: FileMeta = {
  Icon: ICONS.document,
  className: "opacity-75 grayscale",
  type: "File",
};

const KNOWN_EXTS = new Set(Object.keys(EXT_META));

export function fileExtension(name: string): string | null {
  const clean = name.trim().split(/[?#]/)[0];
  const base = clean.split(/[\\/]/).pop() || clean;
  const compound = base.toLowerCase().match(/\.(d\.ts)$/);
  if (compound) return compound[1];
  const match = base.match(/\.([a-z0-9]{1,10})$/i);
  return match ? match[1].toLowerCase() : null;
}

/** Conservative filename/path recognition for inline-code rendering. */
export function isFileLike(name?: string | null): boolean {
  if (!name) return false;
  const value = name.trim();
  const pathToken = value.split(/[?#]/)[0];
  if (
    !pathToken ||
    pathToken.length > 260 ||
    /[\r\n<>()[\]{}=`;|]/.test(pathToken) ||
    /\s[+*]\s|::/.test(pathToken)
  ) {
    return false;
  }
  const ext = fileExtension(value);
  return !!ext && KNOWN_EXTS.has(ext);
}

export function getFileMeta(name: string, mimeType?: string | null): FileMeta {
  const ext = fileExtension(name);
  if (ext && EXT_META[ext]) return EXT_META[ext];
  if (mimeType) {
    const match = MIME_META.find(([pattern]) => pattern.test(mimeType));
    if (match) return match[1];
  }
  return FALLBACK_META;
}

export function fileTypeLabel(name: string, mimeType?: string | null): string {
  const meta = getFileMeta(name, mimeType);
  if (meta !== FALLBACK_META) return meta.type;
  return fileExtension(name)?.toUpperCase() || meta.type;
}

export function fileBasename(name: string): string {
  const clean = name.trim().split(/[?#]/)[0];
  return clean.split(/[\\/]/).pop() || clean;
}

export const FileTypeIcon: React.FC<{
  name: string;
  mimeType?: string | null;
  className?: string;
}> = ({ name, mimeType, className }) => {
  const { Icon, className: iconClassName } = getFileMeta(name, mimeType);
  return <Icon className={cn("h-4 w-4 shrink-0", iconClassName, className)} />;
};

export const FileChip: React.FC<{
  /** Human-friendly label; preserved exactly apart from path basename. */
  name: string;
  href?: string;
  className?: string;
  /** Real filename/path used for icon detection when name is a friendly label. */
  iconName?: string;
  mimeType?: string | null;
}> = ({ name, href, className, iconName, mimeType }) => {
  const label = iconName ? name : fileBasename(name);
  const inner = (
    <>
      <FileTypeIcon name={iconName ?? name} mimeType={mimeType} />
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
          "inline-flex max-w-full items-center gap-1.5 align-middle text-sky-700 underline decoration-sky-700/35 underline-offset-2 hover:decoration-sky-700 dark:text-sky-400 dark:decoration-sky-400/40",
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
