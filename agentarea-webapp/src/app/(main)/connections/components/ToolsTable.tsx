import { useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronRight } from "lucide-react";
import { Streamdown } from "streamdown";
import Table from "@/components/Table/Table";

interface Tool {
  name: string;
  description: string;
  method?: string;
  path?: string;
}

const METHOD_STYLES: Record<string, string> = {
  GET: "bg-emerald-100 text-emerald-700 border-emerald-300 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800",
  POST: "bg-sky-100 text-sky-700 border-sky-300 dark:bg-sky-950/40 dark:text-sky-300 dark:border-sky-800",
  PUT: "bg-amber-100 text-amber-700 border-amber-300 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-800",
  PATCH: "bg-sky-100 text-sky-700 border-sky-300 dark:bg-sky-950/40 dark:text-sky-300 dark:border-sky-800",
  DELETE: "bg-rose-100 text-rose-700 border-rose-300 dark:bg-rose-950/40 dark:text-rose-300 dark:border-rose-800",
};

function MethodBadge({ method }: { method?: string }) {
  const m = (method || "").toUpperCase();
  const style = METHOD_STYLES[m] ?? "bg-muted text-muted-foreground border-border";
  return (
    <span
      className={`inline-block w-[60px] shrink-0 rounded border px-1.5 py-0.5 text-center font-mono text-[10px] font-semibold uppercase tracking-wider ${style}`}
    >
      {m || "—"}
    </span>
  );
}

// Use the first non-version segment of the path as the group key.
// e.g. /acquiring/v1.0/payments → "acquiring", /open-banking/v1.0/accounts → "open-banking".
function pathGroup(path?: string): string {
  if (!path) return "Other";
  const segments = path.split("/").filter(Boolean);
  for (const seg of segments) {
    if (!/^v?\d/.test(seg)) return seg;
  }
  return segments[0] || "Other";
}

function prettyGroup(key: string): string {
  return key
    .replace(/[-_]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

interface Row {
  id: string;
  name: string;
  description: string;
  method?: string;
  path?: string;
}

function MCPToolRow({ name, description }: { name: string; description: string }) {
  const [expanded, setExpanded] = useState(false);
  const hasDescription = !!description;
  const canExpand = hasDescription;

  return (
    <div
      className={`grid grid-cols-[minmax(180px,260px)_1fr_auto] items-start gap-3 px-3 py-2 border-t first:border-t-0 ${
        canExpand ? "cursor-pointer hover:bg-muted/30" : ""
      }`}
      onClick={() => canExpand && setExpanded((v) => !v)}
    >
      <span className="font-mono text-xs font-medium break-all pt-0.5">{name}</span>
      <div className="min-w-0">
        {hasDescription ? (
          expanded ? (
            <Streamdown className="prose prose-sm dark:prose-invert max-w-none">
              {description}
            </Streamdown>
          ) : (
            <p className="line-clamp-2 text-xs text-muted-foreground">{description}</p>
          )
        ) : (
          <span className="text-xs italic text-muted-foreground">—</span>
        )}
      </div>
      {canExpand ? (
        <ChevronRight
          className={`h-3.5 w-3.5 mt-1 text-muted-foreground transition-transform ${
            expanded ? "rotate-90" : ""
          }`}
        />
      ) : (
        <span className="w-3.5" />
      )}
    </div>
  );
}

function ToolsGroup({
  groupKey,
  rows,
  defaultOpen,
}: {
  groupKey: string;
  rows: Row[];
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const t = useTranslations("OpenAPIConnection");
  return (
    <div className="rounded-lg border">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left hover:bg-muted/40"
      >
        <div className="flex items-center gap-2">
          <ChevronRight
            className={`h-3.5 w-3.5 text-muted-foreground transition-transform ${open ? "rotate-90" : ""}`}
          />
          <span className="text-sm font-medium">{prettyGroup(groupKey)}</span>
          <span className="text-xs text-muted-foreground">({rows.length})</span>
        </div>
      </button>
      {open && (
        <div className="border-t">
          <Table
            data={rows}
            columns={[
              {
                header: t("method"),
                accessor: "method",
                render: (value: string) => <MethodBadge method={value} />,
              },
              {
                header: t("operation"),
                accessor: "description",
                render: (
                  value: string,
                  row: { name: string; description: string; path?: string }
                ) => (
                  <div className="flex flex-col gap-0.5">
                    {value ? (
                      <Streamdown className="prose prose-sm dark:prose-invert max-w-none">
                        {value}
                      </Streamdown>
                    ) : (
                      <span className="text-sm font-medium">{row.name}</span>
                    )}
                    {row.path && (
                      <span className="break-all font-mono text-[11px] text-muted-foreground">
                        {row.path}
                      </span>
                    )}
                    <span className="break-all font-mono text-[10px] text-muted-foreground/70">
                      {row.name}
                    </span>
                  </div>
                ),
              },
            ]}
          />
        </div>
      )}
    </div>
  );
}

export function ToolsTable({ tools, label }: { tools: Tool[]; label?: string }) {
  // OpenAPI tools carry method/path and group naturally by path prefix.
  // MCP tools have neither, so render a flat list keyed by name.
  const isOpenAPI = tools.some((t) => !!t.path);

  if (!isOpenAPI) {
    const rows: Row[] = tools.map((t) => ({
      id: t.name,
      name: t.name,
      description: t.description,
    }));
    rows.sort((a, b) =>
      (a.description || a.name).toLowerCase().localeCompare(
        (b.description || b.name).toLowerCase()
      )
    );

    return (
      <div className="space-y-2">
        {label && (
          <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {label}
          </div>
        )}
        <div className="rounded-lg border overflow-hidden">
          <div className="grid grid-cols-[minmax(180px,260px)_1fr_auto] gap-3 px-3 py-2 bg-muted/40 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            <span>Name</span>
            <span>Description</span>
            <span className="w-3.5" />
          </div>
          {rows.map((row) => (
            <MCPToolRow key={row.id} name={row.name} description={row.description} />
          ))}
        </div>
      </div>
    );
  }

  // OpenAPI mode — group by path prefix; sort within group by human description
  // so the long autogenerated operationIds don't drive the order.
  const grouped = tools.reduce<Record<string, Row[]>>((acc, t) => {
    const key = pathGroup(t.path);
    (acc[key] ||= []).push({
      id: t.name,
      name: t.name,
      description: t.description,
      method: t.method,
      path: t.path,
    });
    return acc;
  }, {});

  const groups = Object.entries(grouped)
    .map(([key, rows]) => ({
      key,
      rows: [...rows].sort((a, b) => {
        const ka = (a.description || a.name).toLowerCase();
        const kb = (b.description || b.name).toLowerCase();
        return ka.localeCompare(kb);
      }),
    }))
    .sort((a, b) => a.key.localeCompare(b.key));

  // Auto-expand the first group when there are several so the page isn't an
  // empty-looking accordion; collapse the rest so 70-tool specs stay scannable.
  const defaultOpenAll = groups.length <= 2;

  return (
    <div className="space-y-2">
      {label && (
        <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </div>
      )}
      <div className="space-y-2">
        {groups.map((g, i) => (
          <ToolsGroup
            key={g.key}
            groupKey={g.key}
            rows={g.rows}
            defaultOpen={defaultOpenAll || i === 0}
          />
        ))}
      </div>
    </div>
  );
}
