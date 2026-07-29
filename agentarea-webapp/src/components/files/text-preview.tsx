"use client";

import { useMemo } from "react";
import { Streamdown } from "streamdown";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

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
  if (ext === "md" || ext === "mdx" || ext === "markdown") return { kind: "markdown" };
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

function CsvPreview({ text, delimiter }: { text: string; delimiter: string }) {
  const rows = useMemo(() => parseDelimited(text, delimiter), [text, delimiter]);

  if (rows.length === 0) {
    return <div className="p-4 text-sm text-muted-foreground">Empty file.</div>;
  }

  const [header, ...body] = rows;
  const truncated = body.length > MAX_CSV_ROWS;
  const visible = truncated ? body.slice(0, MAX_CSV_ROWS) : body;

  return (
    <div className="p-2">
      <div className="overflow-x-auto rounded-md border bg-background">
        <Table>
          <TableHeader>
            <TableRow>
              {header.map((cell, i) => (
                <TableHead key={i} className="whitespace-nowrap text-xs">
                  {cell}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {visible.map((r, i) => (
              <TableRow key={i}>
                {header.map((_, j) => (
                  <TableCell key={j} className="whitespace-nowrap py-1.5 text-xs">
                    {r[j] ?? ""}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {truncated && (
        <div className="px-1 py-2 text-xs text-muted-foreground">
          Showing first {MAX_CSV_ROWS} rows.
        </div>
      )}
    </div>
  );
}

function fenceFor(text: string): string {
  const longest = text.match(/`+/g)?.reduce((a, b) => (b.length > a.length ? b : a), "") ?? "";
  return "`".repeat(Math.max(4, longest.length + 1));
}

function CodePreview({ text, lang }: { text: string; lang: string }) {
  const fence = fenceFor(text);
  return (
    <Streamdown className="max-w-none p-4 text-xs [&_pre]:my-0">
      {`${fence}${lang}\n${text}\n${fence}`}
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
      return <pre className="whitespace-pre-wrap break-words p-4 text-xs font-mono">{text}</pre>;
  }
}
