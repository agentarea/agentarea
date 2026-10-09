"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { Streamdown } from "streamdown";
import Table, { type Column } from "@/components/Table/Table";
import { cn } from "@/lib/utils";
import { indentJson } from "./indent-json";

const CODE_LANGS: Record<string, string> = {
  json: "json",
  yaml: "yaml",
  yml: "yaml",
  py: "python",
  js: "javascript",
  jsx: "jsx",
  ts: "typescript",
  tsx: "tsx",
  go: "go",
  rs: "rust",
  html: "html",
  css: "css",
  sh: "bash",
  toml: "toml",
  ini: "ini",
  xml: "xml",
  sql: "sql",
};

type TextVariant =
  | { kind: "markdown" }
  | { kind: "csv"; delimiter: string }
  | { kind: "code"; lang: string }
  | { kind: "plain" };

export function textVariantOf(path: string): TextVariant {
  const ext = path.split(".").pop()?.toLowerCase() || "";
  if (ext === "md" || ext === "mdx" || ext === "markdown")
    return { kind: "markdown" };
  if (ext === "csv") return { kind: "csv", delimiter: "," };
  if (ext === "tsv") return { kind: "csv", delimiter: "\t" };
  const lang = CODE_LANGS[ext];
  if (lang) return { kind: "code", lang };
  return { kind: "plain" };
}

const MAX_CSV_ROWS = 500;

function parseDelimited(text: string, delimiter: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let inQuotes = false;

  const pushField = () => {
    row.push(field);
    field = "";
  };
  const pushRow = () => {
    pushField();
    rows.push(row);
    row = [];
  };

  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += ch;
      }
    } else if (ch === '"' && field === "") {
      inQuotes = true;
    } else if (ch === delimiter) {
      pushField();
    } else if (ch === "\n") {
      pushRow();
      if (rows.length > MAX_CSV_ROWS + 1) break;
    } else if (ch !== "\r") {
      field += ch;
    }
  }
  if (field !== "" || row.length > 0) pushRow();

  return rows.filter((r) => !(r.length === 1 && r[0] === ""));
}

/** One data row of a delimited file; `id` is its line number under the header. */
type CsvRow = { id: number; cells: string[] };

function CsvPreview({ text, delimiter }: { text: string; delimiter: string }) {
  const t = useTranslations("FilesPage");
  const rows = useMemo(
    () => parseDelimited(text, delimiter),
    [text, delimiter]
  );

  if (rows.length === 0) {
    return (
      <div className="p-4 text-sm text-muted-foreground">{t("emptyFile")}</div>
    );
  }

  const [header, ...body] = rows;
  const truncated = body.length > MAX_CSV_ROWS;
  const visible = truncated ? body.slice(0, MAX_CSV_ROWS) : body;
  const data: CsvRow[] = visible.map((cells, i) => ({ id: i + 1, cells }));
  // The same table as every list in the app; a row number to find a line by.
  const columns: Column<CsvRow>[] = [
    {
      header: "#",
      accessor: "id",
      headerClassName: "w-10",
      cellClassName: "w-10 text-xs tabular-nums text-muted-foreground",
    },
    ...header.map((name, column) => ({
      header: name,
      accessor: `column-${column}`,
      headerClassName: "whitespace-nowrap",
      cellClassName: "whitespace-nowrap text-xs",
      render: (_: unknown, row?: CsvRow) => row?.cells[column] ?? "",
    })),
  ];

  return (
    <div className="space-y-2 p-4">
      <Table<CsvRow> data={data} columns={columns} />
      <p className="text-xs text-muted-foreground">
        {truncated
          ? t("csvTruncated", { count: MAX_CSV_ROWS })
          : t("csvRows", { count: body.length })}
      </p>
    </div>
  );
}

function fenceFor(text: string): string {
  const longest =
    text.match(/`+/g)?.reduce((a, b) => (b.length > a.length ? b : a), "") ??
    "";
  return "`".repeat(Math.max(4, longest.length + 1));
}

/**
 * Streamdown draws a code block as a chat message's: a card with the
 * language and its own copy and download. A file's viewer already names the
 * file and carries those actions, so the block is flattened to its body — one
 * card around the code — and long lines scroll instead of being clipped.
 */
const FILE_CODE_BLOCK = cn(
  "[&_[data-streamdown=code-block]]:my-0 [&_[data-streamdown=code-block]]:gap-0 [&_[data-streamdown=code-block]]:rounded-none [&_[data-streamdown=code-block]]:border-0 [&_[data-streamdown=code-block]]:bg-transparent [&_[data-streamdown=code-block]]:p-0",
  "[&_[data-streamdown=code-block-header]]:hidden",
  "[&_[data-streamdown=code-block-body]]:overflow-x-auto [&_[data-streamdown=code-block-body]]:text-xs"
);

function CodePreview({ text, lang }: { text: string; lang: string }) {
  const shown = lang === "json" ? indentJson(text) : text;
  const fence = fenceFor(shown);
  return (
    <Streamdown
      controls={false}
      className={cn("max-w-none p-4 text-xs [&_pre]:my-0", FILE_CODE_BLOCK)}
    >
      {`${fence}${lang}\n${shown}\n${fence}`}
    </Streamdown>
  );
}

export function TextPreview({ path, text }: { path: string; text: string }) {
  const variant = textVariantOf(path);

  switch (variant.kind) {
    case "markdown":
      return (
        <Streamdown className="prose prose-sm max-w-none p-4 dark:prose-invert">
          {text}
        </Streamdown>
      );
    case "csv":
      return <CsvPreview text={text} delimiter={variant.delimiter} />;
    case "code":
      return <CodePreview text={text} lang={variant.lang} />;
    case "plain":
      return (
        <pre className="whitespace-pre-wrap break-words p-4 text-xs font-mono">
          {text}
        </pre>
      );
  }
}
