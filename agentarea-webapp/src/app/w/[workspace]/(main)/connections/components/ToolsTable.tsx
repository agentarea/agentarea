"use client";

import { useMemo, useState, type ComponentProps, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { ChevronRight, Info, Users } from "lucide-react";
import { AgentAvatar } from "@/components/AgentAvatar";
import { MessageMarkdown } from "@/components/Chat/MessageMarkdown";
import EmptyState from "@/components/EmptyState";
import SearchInput from "@/components/SearchInput";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import Table, { type Column } from "@/components/Table/Table";
import { Badge } from "@/components/ui/badge";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";
import { CollapsibleGroup } from "@/components/ui/group-header";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  markdownBeyondSummary,
  markdownExceedsPreview,
  splitMarkdownSummary,
} from "@/lib/markdown-plain-text";
import Link from "@/components/WorkspaceLink";
import { useIsBelow } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";
import {
  OTHER_GROUP_KEY,
  type PrincipalLookup,
  type Tool,
  type ToolAnnotations,
  type ToolFacet,
  type ToolPrincipal,
  type ToolRow,
  type ToolsTableConsumer,
  titleAddsToName,
} from "../tool-facets";
import { useToolFacets } from "../useToolFacets";

const TOOLS_NAMESPACE = "MCPServersPage.instanceDetail.tools";

// Map each server hint to a badge. Only hints the server explicitly set reach
// the frontend (None-valued ones are dropped on the backend), so presence of
// the key is enough to decide whether to render.
const HINT_BADGES: {
  key: "readOnlyHint" | "destructiveHint" | "idempotentHint" | "openWorldHint";
  variant: ComponentProps<typeof Badge>["variant"];
}[] = [
  { key: "readOnlyHint", variant: "success" },
  { key: "destructiveHint", variant: "rose" },
  { key: "idempotentHint", variant: "slate" },
  { key: "openWorldHint", variant: "amber" },
];

function AnnotationBadges({ annotations }: { annotations?: ToolAnnotations }) {
  const t = useTranslations(`${TOOLS_NAMESPACE}.hints`);
  const hintBadges = HINT_BADGES.filter((b) => annotations?.[b.key] === true);
  if (!hintBadges.length) return null;

  return (
    <div className="flex flex-wrap items-center gap-1">
      {hintBadges.map((b) => (
        <Badge key={b.key} variant={b.variant} size="sm">
          {t(b.key)}
        </Badge>
      ))}
    </div>
  );
}

function hasHints(annotations?: ToolAnnotations): boolean {
  return HINT_BADGES.some((b) => annotations?.[b.key] === true);
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

/** One labelled part of an open tool row, with an optional ⓘ explanation. */
function DetailSection({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-1.5">
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        {label}
        {hint && (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  onClick={(e) => e.stopPropagation()}
                  className="inline-flex text-muted-foreground/60 hover:text-muted-foreground"
                  aria-label={label}
                >
                  <Info className="h-3 w-3" />
                </button>
              </TooltipTrigger>
              <TooltipContent className="max-w-[260px]">{hint}</TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}
      </div>
      {children}
    </section>
  );
}

/**
 * Who holds the tool, inline: a small avatar and the name, how the agent got
 * the tool and approval as quiet text after it; hovering tints only the name.
 */
function PrincipalList({ principals }: { principals: ToolPrincipal[] }) {
  const t = useTranslations(TOOLS_NAMESPACE);

  return principals.length === 0 ? (
    <p className="text-[12.5px] text-muted-foreground">{t("equippedNone")}</p>
  ) : (
    <div className="-mx-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
      {principals.map((principal) => (
        <Link
          key={principal.agentId}
          href={`/agents/${principal.slug ?? principal.agentId}`}
          className="group/agent inline-flex h-7 items-center gap-1.5 rounded-md px-1.5 text-[12.5px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          <AgentAvatar
            agent={{ id: principal.agentId, name: principal.name }}
            size="xs"
          />
          <span className="font-medium transition-colors group-hover/agent:text-accent">
            {principal.name}
          </span>
          {principal.viaAllTools && (
            <span className="text-muted-foreground">· {t("allToolsGrant")}</span>
          )}
          {principal.needsConfirm && (
            <span className="text-amber-600 dark:text-amber-400">
              · {t("approval")}
            </span>
          )}
        </Link>
      ))}
    </div>
  );
}

/** Who holds a tool, as a count; hovering lists them. */
function EquippedCount({ principals }: { principals: ToolPrincipal[] }) {
  const t = useTranslations(TOOLS_NAMESPACE);
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={cn(
              "inline-flex cursor-default items-center gap-1 text-[12px] tabular-nums",
              principals.length ? "text-foreground/70" : "text-muted-foreground"
            )}
          >
            <Users className="h-3 w-3" />
            {principals.length}
          </span>
        </TooltipTrigger>
        <TooltipContent className="max-w-[280px]">
          {principals.length === 0 ? (
            t("equippedNone")
          ) : (
            <div className="space-y-1">
              <div className="font-medium">{t("equippedBy")}</div>
              {principals.map((principal) => (
                <div key={principal.agentId} className="flex items-center gap-1.5">
                  <span>{principal.name}</span>
                  {principal.viaAllTools && (
                    <span className="opacity-70">· {t("allToolsGrant")}</span>
                  )}
                  {principal.needsConfirm && (
                    <span className="opacity-70">· {t("approval")}</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

/**
 * A description's first paragraph in a two-line cell, with its own inline
 * formatting (code, bold, links) kept; what follows is for the open row.
 */
function DescriptionSummary({ markdown }: { markdown: string }) {
  return (
    <MessageMarkdown
      content={splitMarkdownSummary(markdown).summary}
      className="line-clamp-2 !text-[12.5px] !leading-[18px] !text-muted-foreground [&_p]:!my-0 [&_p]:inline"
    />
  );
}

/**
 * Name cell, the same shape on every row: the name agents call in mono, and
 * the server's human title under it when it says more than the name.
 */
function ToolName({ row }: { row: ToolRow }) {
  const rawTitle = row.title || row.annotations?.title;
  // A title that only spells the name out would repeat it under itself.
  const title = titleAddsToName(row.name, rawTitle) ? rawTitle : null;
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span className="break-all font-mono text-[12.5px] font-medium">{row.name}</span>
      {title && (
        <span className="break-words text-[12px] text-muted-foreground">{title}</span>
      )}
    </div>
  );
}

/** Columns for MCP tool rows: name, description, who holds it, expand chevron. */
function useMcpColumns(
  principalsFor: PrincipalLookup | null,
  isOpen: (row: ToolRow) => boolean,
  showHints: boolean,
  viewport: Viewport
): Column<ToolRow>[] {
  const t = useTranslations(TOOLS_NAMESPACE);
  const { narrow, mobile } = viewport;
  const columns: Column<ToolRow>[] = [
    {
      accessor: "name",
      header: t("columns.name"),
      // Below lg there is no description column to take the slack, so the
      // name column does.
      headerClassName: "lg:w-[28%]",
      render: (_value, row) => (row ? <ToolName row={row} /> : null),
    },
  ];
  // Below lg the open row carries the description. The column is left out,
  // not just hidden: a fixed-layout table would still hand the hidden
  // column the spare width and leave a blank strip. The CSS `hidden` covers
  // the first render, before the viewport is known.
  if (!narrow) {
    columns.push({
      accessor: "description",
      header: t("columns.description"),
      // Below lg the column gives way and the open row carries the description.
      headerClassName: "hidden lg:table-cell",
      cellClassName: "hidden lg:table-cell",
      // Only the opening paragraph: what follows it is what the open row shows.
      render: (value) =>
        value ? (
          <DescriptionSummary markdown={value as string} />
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    });
  }
  // On a phone the hints go to the open row too, so the name keeps its width.
  if (showHints && !mobile) {
    columns.push({
      accessor: "annotations",
      header: t("columns.hints"),
      headerClassName: "w-[200px]",
      render: (_value, row) => <AnnotationBadges annotations={row?.annotations} />,
    });
  }
  if (principalsFor) {
    columns.push({
      accessor: "equipped",
      header: mobile ? t("columns.agents") : t("columns.equipped"),
      headerClassName: mobile ? "w-[76px]" : "w-[130px]",
      render: (_value, row) =>
        row ? <EquippedCount principals={principalsFor(row.name)} /> : null,
    });
  }
  columns.push({
    accessor: "expand",
    header: "",
    headerClassName: mobile ? "w-[36px]" : "w-[44px]",
    render: (_value, row) =>
      row && canExpand(row, principalsFor, viewport) ? (
        <ChevronRight
          className={cn(
            "h-3.5 w-3.5 text-muted-foreground transition-transform",
            isOpen(row) && "rotate-90"
          )}
        />
      ) : null,
  });
  return columns;
}

/**
 * What a tool row opens into, limited to what the row cannot show: the part
 * of the description its one-paragraph summary leaves out, and who holds the
 * tool by name (the row has only the count). The hints are in their column.
 */
/**
 * How much of a tool row fits on screen. Below lg the description column gives
 * way, on a phone the hints column too; what the row drops, the open row shows.
 */
interface Viewport {
  narrow: boolean;
  mobile: boolean;
}

function ToolDetails({
  row,
  principals,
  viewport,
}: {
  row: ToolRow;
  principals: ToolPrincipal[] | null;
  viewport: Viewport;
}) {
  const t = useTranslations(TOOLS_NAMESPACE);
  const { narrow } = viewport;
  return (
    <div className="space-y-4 py-1">
      {descriptionInDetails(row, narrow) && (
        <DetailSection label={t("columns.description")}>
          <MessageMarkdown
            content={
              narrow ? row.description : markdownBeyondSummary(row.description)
            }
            className="!text-[13px] !leading-[20px]"
          />
        </DetailSection>
      )}
      {hintsInDetails(row, viewport) && (
        <DetailSection label={t("columns.hints")}>
          <AnnotationBadges annotations={row.annotations} />
        </DetailSection>
      )}
      {principals !== null && (
        <DetailSection label={t("equippedBy")} hint={t("equippedHint")}>
          <PrincipalList principals={principals} />
        </DetailSection>
      )}
    </div>
  );
}

const descriptionInDetails = (row: ToolRow, narrow: boolean) =>
  Boolean(row.description) &&
  (narrow || markdownExceedsPreview(row.description));

const hintsInDetails = (row: ToolRow, { mobile }: Viewport) =>
  mobile && hasHints(row.annotations);

/** A row opens only when its details hold something the row does not show. */
const canExpand = (
  row: ToolRow,
  principalsFor: PrincipalLookup | null,
  viewport: Viewport
) =>
  principalsFor !== null ||
  descriptionInDetails(row, viewport.narrow) ||
  hintsInDetails(row, viewport);

function McpToolsTable({
  rows,
  principalsFor,
  isOpen,
  toggle,
  viewport,
}: {
  rows: ToolRow[];
  principalsFor: PrincipalLookup | null;
  isOpen: (row: ToolRow) => boolean;
  toggle: (row: ToolRow) => void;
  viewport: Viewport;
}) {
  const columns = useMcpColumns(
    principalsFor,
    isOpen,
    rows.some((row) => hasHints(row.annotations)),
    viewport
  );
  return (
    <Table
      data={rows}
      columns={columns}
      className="table-fixed"
      onRowClick={(row) => canExpand(row, principalsFor, viewport) && toggle(row)}
      rowProps={(row) =>
        canExpand(row, principalsFor, viewport)
          ? {}
          : { className: "cursor-default hover:bg-transparent dark:hover:bg-transparent" }
      }
      isExpanded={isOpen}
      renderExpanded={(row) => (
        <ToolDetails
          row={row}
          principals={principalsFor ? principalsFor(row.name) : null}
          viewport={viewport}
        />
      )}
    />
  );
}

function OpenApiToolsTable({ rows }: { rows: ToolRow[] }) {
  const t = useTranslations("OpenAPIConnection");
  return (
    <Table
      data={rows}
      className="table-fixed"
      columns={[
        {
          header: t("method"),
          accessor: "method",
          headerClassName: "w-[96px]",
          render: (value) => <MethodBadge method={value as string} />,
        },
        {
          header: t("operation"),
          accessor: "description",
          render: (value, row) => (
            <div className="flex flex-col gap-0.5">
              {value ? (
                <DescriptionSummary markdown={value as string} />
              ) : (
                <span className="text-sm font-medium">{row?.name}</span>
              )}
              {row?.path && (
                <span className="break-all font-mono text-[11px] text-muted-foreground">
                  {row.path}
                </span>
              )}
              <span className="break-all font-mono text-[10px] text-muted-foreground">
                {row?.name}
              </span>
            </div>
          ),
        },
      ]}
    />
  );
}

// Hard ceiling on rows rendered in one flat list — a 400-tool server otherwise
// puts 400 expandable rows into the DOM on first paint.
const FLAT_RENDER_CAP = 150;

export type ToolFacetsState = ReturnType<typeof useToolFacets>;

/**
 * Facet tabs, search and the caller's controls for a tools list, laid out as a
 * subheader toolbar. A page with a subheader band puts it there; `ToolsTable`
 * draws it inline otherwise.
 */
export function ToolsToolbar({
  facets,
  controls,
}: {
  facets: ToolFacetsState;
  controls?: ReactNode;
}) {
  const t = useTranslations(TOOLS_NAMESPACE);
  const {
    setQuery,
    facet,
    setFacet,
    principalsFor,
    isOpenAPI,
    hasDestructive,
    hasReadOnly,
    facetCounts,
  } = facets;

  const facetItems: { value: ToolFacet; label: string; count: number }[] = [
    { value: "all", label: t("facets.all"), count: facetCounts.all },
    ...(principalsFor
      ? [
          { value: "equipped" as const, label: t("facets.equipped"), count: facetCounts.equipped },
          { value: "unequipped" as const, label: t("facets.unequipped"), count: facetCounts.unequipped },
        ]
      : []),
    ...(hasDestructive
      ? [{ value: "destructive" as const, label: t("facets.destructive"), count: facetCounts.destructive }]
      : []),
    ...(hasReadOnly
      ? [{ value: "readOnly" as const, label: t("facets.readOnly"), count: facetCounts.readOnly }]
      : []),
  ];

  return (
    <SubheaderToolbar
      categories={
        !isOpenAPI && facetItems.length > 1 ? (
          <div role="group" aria-label={t("facetsLabel")} className="min-w-0">
            <CountSegmentedControl
              items={facetItems}
              value={facet}
              onChange={setFacet}
              variant="subtle"
              className="max-w-full"
              layoutId="tools-facet-control"
            />
          </div>
        ) : undefined
      }
      search={
        <SearchInput
          onDebouncedChange={setQuery}
          delay={200}
          placeholder={t("searchPlaceholder")}
        />
      }
      controls={controls}
    />
  );
}

export function ToolsTable({
  tools,
  label,
  consumers,
  facets: givenFacets,
}: {
  tools: Tool[];
  label?: string;
  /**
   * Agents attaching this connection. `undefined`/`null` (OpenAPI detail,
   * catalog previews, data still loading) hides the principal column rather
   * than rendering a misleading zero.
   */
  consumers?: ToolsTableConsumer[] | null;
  /**
   * Filter state owned by a page that draws `ToolsToolbar` in its own
   * subheader; the table then shows no toolbar of its own.
   */
  facets?: ToolFacetsState;
}) {
  const t = useTranslations(TOOLS_NAMESPACE);
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  // Tailwind's lg and md: what the row drops below them (see the columns).
  const narrow = useIsBelow(1024);
  const mobile = useIsBelow(768);
  const viewport = useMemo(() => ({ narrow, mobile }), [narrow, mobile]);
  const ownFacets = useToolFacets(tools, consumers);
  const facets = givenFacets ?? ownFacets;
  const {
    principalsFor,
    isOpenAPI,
    searching,
    mcpRows,
    mcpGroups,
    pathGroups,
  } = facets;

  const isOpen = (row: ToolRow) => open.has(row.id);
  const toggle = (row: ToolRow) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(row.id)) next.delete(row.id);
      else next.add(row.id);
      return next;
    });

  // Under a page's subheader band the 36px group header carries its own air,
  // so the list is pulled up until the first header sits just under the band.
  const groupsClassName = cn("flex flex-col gap-1", givenFacets && "-mt-4");

  const empty = (
    <EmptyState
      title={t("empty")}
      description={t("emptyDescription")}
      iconsType="mcp"
      action={
        facets.facet !== "all"
          ? { label: t("showAll"), onClick: () => facets.setFacet("all") }
          : undefined
      }
    />
  );
  let body: ReactNode;
  if (!isOpenAPI) {
    const truncated = !mcpGroups.length && mcpRows.length > FLAT_RENDER_CAP;
    body =
      mcpRows.length === 0 ? (
        empty
      ) : mcpGroups.length > 0 ? (
        <div className={groupsClassName}>
          {mcpGroups.map((group) => {
            return (
              <CollapsibleGroup
                key={group.key}
                variant="plain"
                defaultOpen={group.open}
                label={
                  group.key === OTHER_GROUP_KEY
                    ? t("otherGroup")
                    : prettyGroup(group.label)
                }
                count={group.rows.length}
              >
                <McpToolsTable
                  rows={group.rows}
                  principalsFor={principalsFor}
                  isOpen={isOpen}
                  toggle={toggle}
                  viewport={viewport}
                />
              </CollapsibleGroup>
            );
          })}
        </div>
      ) : (
        <>
          <McpToolsTable
            rows={truncated ? mcpRows.slice(0, FLAT_RENDER_CAP) : mcpRows}
            principalsFor={principalsFor}
            isOpen={isOpen}
            toggle={toggle}
            viewport={viewport}
          />
          {truncated && (
            <p className="note">
              {t("truncated", { shown: FLAT_RENDER_CAP, total: mcpRows.length })}
            </p>
          )}
        </>
      );
  } else {
    // Auto-expand the first group when there are several so the page isn't an
    // empty-looking accordion; collapse the rest so 70-tool specs stay scannable.
    // A live search already narrowed the set, so every remaining group opens.
    const defaultOpenAll = pathGroups.length <= 2 || searching;
    body =
      pathGroups.length === 0 ? (
        empty
      ) : (
        <div className={groupsClassName}>
          {pathGroups.map((group, i) => (
            <CollapsibleGroup
              key={group.key}
              variant="plain"
              defaultOpen={defaultOpenAll || i === 0}
              label={prettyGroup(group.key)}
              count={group.rows.length}
            >
              <OpenApiToolsTable rows={group.rows} />
            </CollapsibleGroup>
          ))}
        </div>
      );
  }

  return (
    <div className="space-y-3">
      {label && <p className="text-sm font-medium">{label}</p>}
      {!givenFacets && (
        <div className="flex h-9 items-center">
          <ToolsToolbar facets={facets} />
        </div>
      )}
      {body}
    </div>
  );
}
