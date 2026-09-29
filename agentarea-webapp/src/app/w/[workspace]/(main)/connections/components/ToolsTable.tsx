"use client";

import { useState, type ComponentProps, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import Link from "@/components/WorkspaceLink";
import { ChevronRight, Info, Search, Users } from "lucide-react";
import { Streamdown } from "streamdown";
import Table from "@/components/Table/Table";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import {
  countExplicitGrants,
  OTHER_GROUP_KEY,
  type PrincipalLookup,
  type Tool,
  type ToolAnnotations,
  type ToolPrincipal,
  type ToolRow,
  type ToolsTableConsumer,
} from "../tool-facets";
import { useToolFacets } from "../useToolFacets";

const TOOLS_NAMESPACE = "MCPServersPage.instanceDetail.tools";

// Map each server hint to a badge. Only hints the server explicitly set reach
// the frontend (None-valued ones are dropped on the backend), so presence of
// the key is enough to decide whether to render.
const HINT_BADGES: {
  key: keyof ToolAnnotations;
  label: string;
  variant: ComponentProps<typeof Badge>["variant"];
}[] = [
  { key: "readOnlyHint", label: "read-only", variant: "success" },
  { key: "destructiveHint", label: "destructive", variant: "rose" },
  { key: "idempotentHint", label: "idempotent", variant: "slate" },
  { key: "openWorldHint", label: "open-world", variant: "amber" },
];

function AnnotationBadges({ annotations }: { annotations?: ToolAnnotations }) {
  const hintBadges = HINT_BADGES.filter((b) => annotations?.[b.key] === true);
  if (!hintBadges.length) return null;

  return (
    <div className="flex flex-wrap items-center gap-1">
      {hintBadges.map((b) => (
        <Badge key={b.key} variant={b.variant} size="sm">
          {b.label}
        </Badge>
      ))}
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              onClick={(e) => e.stopPropagation()}
              className="inline-flex text-muted-foreground/60 hover:text-muted-foreground"
              aria-label="About these hints"
            >
              <Info className="h-3 w-3" />
            </button>
          </TooltipTrigger>
          <TooltipContent className="max-w-[240px]">
            Safety hints reported by the MCP server. Not verified by AgentArea —
            informational only.
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
  );
}

const METHOD_STYLES: Record<string, string> = {
  GET: "bg-emerald-100 text-emerald-700 border-emerald-300 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800",
  POST: "bg-sky-100 text-sky-700 border-sky-300 dark:bg-sky-950/40 dark:text-sky-300 dark:border-sky-800",
  PUT: "bg-amber-100 text-amber-700 border-amber-300 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-800",
  PATCH:
    "bg-sky-100 text-sky-700 border-sky-300 dark:bg-sky-950/40 dark:text-sky-300 dark:border-sky-800",
  DELETE:
    "bg-rose-100 text-rose-700 border-rose-300 dark:bg-rose-950/40 dark:text-rose-300 dark:border-rose-800",
};

function MethodBadge({ method }: { method?: string }) {
  const m = (method || "").toUpperCase();
  const style =
    METHOD_STYLES[m] ?? "bg-muted text-muted-foreground border-border";
  return (
    <span
      className={`inline-block w-[60px] shrink-0 rounded border px-1.5 py-0.5 text-center font-mono text-[10px] font-semibold uppercase tracking-wider ${style}`}
    >
      {m || "—"}
    </span>
  );
}

function prettyGroup(key: string): string {
  return key.replace(/[-_]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function PrincipalList({ principals }: { principals: ToolPrincipal[] }) {
  const t = useTranslations(TOOLS_NAMESPACE);

  return (
    <div className="mt-3 space-y-1.5 border-t pt-2">
      <div className="flex items-center gap-1.5">
        <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {t("equippedBy")}
        </span>
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                onClick={(e) => e.stopPropagation()}
                className="inline-flex text-muted-foreground/60 hover:text-muted-foreground"
                aria-label={t("equippedBy")}
              >
                <Info className="h-3 w-3" />
              </button>
            </TooltipTrigger>
            <TooltipContent className="max-w-[260px]">
              {t("equippedHint")}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>
      {principals.length === 0 ? (
        <p className="text-xs italic text-muted-foreground">
          {t("equippedNone")}
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-1.5">
          {principals.map((p) => (
            <Link
              key={p.agentId}
              href={`/agents/${p.slug ?? p.agentId}`}
              onClick={(e) => e.stopPropagation()}
              className="inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] hover:bg-muted/50"
            >
              <span className="font-medium">{p.name}</span>
              {p.viaAllTools && (
                <Badge variant="slate" size="sm">
                  {t("allToolsGrant")}
                </Badge>
              )}
              {p.needsConfirm && (
                <Badge variant="amber" size="sm">
                  {t("approval")}
                </Badge>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function MCPToolRow({
  name,
  title,
  description,
  annotations,
  principals,
}: {
  name: string;
  title?: string;
  description: string;
  annotations?: ToolAnnotations;
  /** `null` when the caller has no consumer data — the column stays empty. */
  principals: ToolPrincipal[] | null;
}) {
  const t = useTranslations(TOOLS_NAMESPACE);
  const [expanded, setExpanded] = useState(false);
  const hasDescription = !!description;
  const canExpand = hasDescription || principals !== null;
  // Per MCP spec, prefer the human-facing title; fall back to annotations.title,
  // then the raw tool name. Show the raw name underneath when a title exists.
  const displayName = title || annotations?.title;

  return (
    <div
      className={`grid grid-cols-[minmax(180px,260px)_1fr_auto_auto] items-start gap-3 px-3 py-2 border-t first:border-t-0 ${
        canExpand ? "cursor-pointer hover:bg-muted/30" : ""
      }`}
      onClick={() => canExpand && setExpanded((v) => !v)}
    >
      <div className="flex flex-col gap-1 pt-0.5 min-w-0">
        {displayName ? (
          <>
            <span className="text-xs font-medium break-words">
              {displayName}
            </span>
            <span className="font-mono text-[10px] text-muted-foreground/70 break-all">
              {name}
            </span>
          </>
        ) : (
          <span className="font-mono text-xs font-medium break-all">
            {name}
          </span>
        )}
        <AnnotationBadges annotations={annotations} />
      </div>
      <div className="min-w-0">
        {hasDescription ? (
          expanded ? (
            <Streamdown className="prose prose-sm dark:prose-invert max-w-none">
              {description}
            </Streamdown>
          ) : (
            <p className="line-clamp-2 text-xs text-muted-foreground">
              {description}
            </p>
          )
        ) : (
          <span className="text-xs italic text-muted-foreground">—</span>
        )}
        {expanded && principals !== null && (
          <PrincipalList principals={principals} />
        )}
      </div>
      {principals !== null ? (
        <span
          className={cn(
            "mt-0.5 inline-flex items-center gap-1 text-[11px] tabular-nums",
            principals.length
              ? "text-foreground/70"
              : "text-muted-foreground/50"
          )}
          title={t("equippedBy")}
        >
          <Users className="h-3 w-3" />
          {principals.length}
        </span>
      ) : (
        <span />
      )}
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
  rows: ToolRow[];
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

function MCPToolsGroup({
  groupLabel,
  rows,
  defaultOpen,
  principalsFor,
}: {
  groupLabel: string;
  rows: ToolRow[];
  defaultOpen: boolean;
  principalsFor: PrincipalLookup | null;
}) {
  const t = useTranslations(TOOLS_NAMESPACE);
  const [open, setOpen] = useState(defaultOpen);
  const granted = countExplicitGrants(rows, principalsFor);

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
          <span className="text-sm font-medium">{prettyGroup(groupLabel)}</span>
          <span className="text-xs text-muted-foreground">({rows.length})</span>
        </div>
        {granted > 0 && (
          <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground tabular-nums">
            <Users className="h-3 w-3" />
            {t("grantedCount", { count: granted })}
          </span>
        )}
      </button>
      {open && (
        <div className="border-t">
          {rows.map((row) => (
            <MCPToolRow
              key={row.id}
              name={row.name}
              title={row.title}
              description={row.description}
              annotations={row.annotations}
              principals={principalsFor ? principalsFor(row.name) : null}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// Hard ceiling on rows rendered in one flat list — a 400-tool server otherwise
// puts 400 expandable rows into the DOM on first paint.
const FLAT_RENDER_CAP = 150;

function FacetChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-md border px-2 py-1 text-[11px] transition-colors",
        active
          ? "border-primary/40 bg-primary/10 text-foreground"
          : "border-border text-muted-foreground hover:bg-muted/50"
      )}
    >
      {children}
    </button>
  );
}

export function ToolsTable({
  tools,
  label,
  consumers,
}: {
  tools: Tool[];
  label?: string;
  /**
   * Agents attaching this connection. `undefined`/`null` (OpenAPI detail,
   * catalog previews, data still loading) hides the principal column rather
   * than rendering a misleading zero.
   */
  consumers?: ToolsTableConsumer[] | null;
}) {
  const t = useTranslations(TOOLS_NAMESPACE);
  const {
    query,
    setQuery,
    facet,
    setFacet,
    principalsFor,
    isOpenAPI,
    hasDestructive,
    hasReadOnly,
    searching,
    filtered,
    facetCounts,
    mcpRows,
    mcpGroups,
    pathGroups,
  } = useToolFacets(tools, consumers);

  const searchAndFacets = (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative min-w-[200px] flex-1">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("searchPlaceholder")}
          className="h-8 pl-8 text-xs"
        />
      </div>
      {!isOpenAPI && (
        <div className="flex flex-wrap items-center gap-1">
          <FacetChip active={facet === "all"} onClick={() => setFacet("all")}>
            {t("facets.all")}
            <span className="ml-1 tabular-nums">{facetCounts.all}</span>
          </FacetChip>
          {principalsFor && (
            <>
              <FacetChip
                active={facet === "equipped"}
                onClick={() => setFacet("equipped")}
              >
                {t("facets.equipped")}
                <span className="ml-1 tabular-nums">
                  {facetCounts.equipped}
                </span>
              </FacetChip>
              <FacetChip
                active={facet === "unequipped"}
                onClick={() => setFacet("unequipped")}
              >
                {t("facets.unequipped")}
                <span className="ml-1 tabular-nums">
                  {facetCounts.unequipped}
                </span>
              </FacetChip>
            </>
          )}
          {hasDestructive && (
            <FacetChip
              active={facet === "destructive"}
              onClick={() => setFacet("destructive")}
            >
              {t("facets.destructive")}
              <span className="ml-1 tabular-nums">
                {facetCounts.destructive}
              </span>
            </FacetChip>
          )}
          {hasReadOnly && (
            <FacetChip
              active={facet === "readOnly"}
              onClick={() => setFacet("readOnly")}
            >
              {t("facets.readOnly")}
              <span className="ml-1 tabular-nums">{facetCounts.readOnly}</span>
            </FacetChip>
          )}
        </div>
      )}
      <span className="text-[11px] text-muted-foreground tabular-nums">
        {t("shown", { shown: filtered.length, total: tools.length })}
      </span>
    </div>
  );

  if (!isOpenAPI) {
    const visibleRows = mcpGroups.length
      ? mcpRows
      : mcpRows.slice(0, FLAT_RENDER_CAP);
    const truncated = !mcpGroups.length && mcpRows.length > FLAT_RENDER_CAP;

    return (
      <div className="space-y-2">
        {label && (
          <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {label}
          </div>
        )}
        {searchAndFacets}

        {mcpRows.length === 0 ? (
          <div className="rounded-lg border p-4 text-xs text-muted-foreground">
            {t("empty")}
          </div>
        ) : mcpGroups.length > 0 ? (
          <div className="space-y-2">
            {mcpGroups.map((group) => (
              <MCPToolsGroup
                key={group.key}
                groupLabel={
                  group.key === OTHER_GROUP_KEY ? t("otherGroup") : group.label
                }
                rows={group.rows}
                defaultOpen={group.open}
                principalsFor={principalsFor}
              />
            ))}
          </div>
        ) : (
          <div className="rounded-lg border overflow-hidden">
            <div className="grid grid-cols-[minmax(180px,260px)_1fr_auto_auto] gap-3 px-3 py-2 bg-muted/40 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              <span>{t("columns.name")}</span>
              <span>{t("columns.description")}</span>
              <span>{principalsFor ? t("columns.equipped") : ""}</span>
              <span className="w-3.5" />
            </div>
            {visibleRows.map((row) => (
              <MCPToolRow
                key={row.id}
                name={row.name}
                title={row.title}
                description={row.description}
                annotations={row.annotations}
                principals={principalsFor ? principalsFor(row.name) : null}
              />
            ))}
            {truncated && (
              <div className="border-t px-3 py-2 text-[11px] text-muted-foreground">
                {t("truncated", {
                  shown: FLAT_RENDER_CAP,
                  total: mcpRows.length,
                })}
              </div>
            )}
          </div>
        )}
      </div>
    );
  }

  // Auto-expand the first group when there are several so the page isn't an
  // empty-looking accordion; collapse the rest so 70-tool specs stay scannable.
  // A live search already narrowed the set, so every remaining group opens.
  const defaultOpenAll = pathGroups.length <= 2 || searching;

  return (
    <div className="space-y-2">
      {label && (
        <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </div>
      )}
      {searchAndFacets}
      {pathGroups.length === 0 ? (
        <div className="rounded-lg border p-4 text-xs text-muted-foreground">
          {t("empty")}
        </div>
      ) : (
        <div className="space-y-2">
          {pathGroups.map((g, i) => (
            <ToolsGroup
              key={g.key}
              groupKey={g.key}
              rows={g.rows}
              defaultOpen={defaultOpenAll || i === 0}
            />
          ))}
        </div>
      )}
    </div>
  );
}
