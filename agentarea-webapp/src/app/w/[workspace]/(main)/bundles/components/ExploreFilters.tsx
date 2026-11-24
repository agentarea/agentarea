"use client";

import { Fragment, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import {
  CircleDollarSign,
  Cloud,
  Gift,
  Globe,
  KeyRound,
  ListFilter,
  Plug,
  Server,
  Wallet,
  X,
} from "lucide-react";
import { parseAsString, parseAsStringLiteral, useQueryState } from "nuqs";
import SearchInput from "@/components/SearchInput";
import ToolbarSelect from "@/components/ToolbarSelect";
import {
  MenuRow,
  MenuSectionLabel,
  MenuSeparator,
} from "@/components/ui/menu-row";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ToolbarButton } from "@/components/ui/toolbar";
import {
  ALL,
  PROTOCOL_LABELS,
  TYPE_KEYS,
  type CatalogType,
} from "./catalog-data";
import type { CategoryFacet } from "./catalog-paging";
import { useExplorePending } from "./explore-pending";

const GLYPH = "h-3.5 w-3.5";

/** The MCP mark as a mask, so it takes the row's text colour. */
function McpGlyph() {
  return (
    <span
      aria-hidden
      className={`block ${GLYPH} bg-current [mask-image:url(/mcp.svg)] [mask-position:center] [mask-repeat:no-repeat] [mask-size:contain] [-webkit-mask-image:url(/mcp.svg)] [-webkit-mask-position:center] [-webkit-mask-repeat:no-repeat] [-webkit-mask-size:contain]`}
    />
  );
}

function CountedLabel({ name, count }: { name: string; count: number }) {
  return (
    <span className="flex min-w-0 items-center gap-2">
      <span className="min-w-0 flex-1 truncate">{name}</span>
      <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
        {count}
      </span>
    </span>
  );
}

/**
 * The catalog search, in the subheader like every other list page. Writes `q`
 * to the URL; the explore Server Component reads it and refetches page 1.
 * Hidden while a detail is open — there is no list to search then.
 */
export function ExploreSearch({ initialType }: { initialType: CatalogType }) {
  const [type] = useQueryState(
    "type",
    parseAsStringLiteral(TYPE_KEYS).withDefault(initialType)
  );
  const [itemId] = useQueryState("item", parseAsString);
  const t = useTranslations("CatalogPage.search");
  if (itemId) return null;
  return (
    <SearchInput
      urlParamName="q"
      urlPath="/explore"
      resetParamNames={["item"]}
      delay={400}
      placeholder={t(type)}
    />
  );
}

type Facet = "protocol" | "hosting" | "pricing";

/**
 * Connection facets as subheader dropdowns: what it speaks, where it runs, how
 * it is paid for. They used to sit in the sidebar above the categories, which
 * hid them below `lg` and pushed the categories down the page.
 */
export function ExploreConnectionFilters({
  initialType,
  protocols,
  hostings,
  pricings,
  compact = false,
}: {
  initialType: CatalogType;
  protocols: CategoryFacet[];
  hostings: CategoryFacet[];
  pricings: CategoryFacet[];
  /** One Filters button instead of three dropdowns — for a phone. */
  compact?: boolean;
}) {
  const pending = useExplorePending();
  const options = {
    shallow: false,
    startTransition: pending?.startFilterTransition,
  };
  const [type] = useQueryState(
    "type",
    parseAsStringLiteral(TYPE_KEYS).withDefault(initialType)
  );
  const [itemId] = useQueryState("item", parseAsString);
  const [protocol, setProtocol] = useQueryState(
    "protocol",
    parseAsString.withDefault(ALL).withOptions(options)
  );
  const [hosting, setHosting] = useQueryState(
    "hosting",
    parseAsString.withDefault(ALL).withOptions(options)
  );
  const [pricing, setPricing] = useQueryState(
    "pricing",
    parseAsString.withDefault(ALL).withOptions(options)
  );
  const [, setItemId] = useQueryState("item", parseAsString);
  const t = useTranslations("CatalogPage.filters");
  const tPricing = useTranslations("CatalogPage.pricing");

  if (type !== "connections" || itemId) return null;

  const setters: Record<Facet, (v: string | null) => unknown> = {
    protocol: setProtocol,
    hosting: setHosting,
    pricing: setPricing,
  };
  const choose = (facet: Facet) => (v: string) => {
    void setters[facet](v === ALL ? null : v);
    void setItemId(null);
  };

  type FacetDef = {
    facet: Facet;
    label: string;
    allIcon: ReactNode;
    facets: CategoryFacet[];
    value: string;
    name: (v: string) => string;
    icon: (v: string) => ReactNode;
  };
  const allDefs: FacetDef[] = [
    {
      facet: "protocol",
      label: t("protocol"),
      allIcon: <Plug className={`${GLYPH} text-muted-foreground`} />,
      facets: protocols,
      value: protocol,
      name: (v) => PROTOCOL_LABELS[v as keyof typeof PROTOCOL_LABELS] ?? v,
      icon: (v) => (v === "mcp" ? <McpGlyph /> : <Globe className={GLYPH} />),
    },
    {
      facet: "hosting",
      label: t("hosting"),
      allIcon: <Server className={`${GLYPH} text-muted-foreground`} />,
      facets: hostings,
      value: hosting,
      name: (v) =>
        v === "vendor" || v === "agentarea" ? t(`hostings.${v}`) : v,
      icon: (v) =>
        v === "vendor" ? (
          <Cloud className={GLYPH} />
        ) : (
          <Server className={GLYPH} />
        ),
    },
    {
      facet: "pricing",
      label: tPricing("facet"),
      allIcon: <Wallet className={`${GLYPH} text-muted-foreground`} />,
      facets: pricings,
      value: pricing,
      name: (v) =>
        v === "paid" || v === "own_key" || v === "free"
          ? tPricing(`kinds.${v}`)
          : v,
      icon: (v) =>
        v === "paid" ? (
          <CircleDollarSign className={GLYPH} />
        ) : v === "own_key" ? (
          <KeyRound className={GLYPH} />
        ) : (
          <Gift className={GLYPH} />
        ),
    },
  ];
  // Nothing to choose between — unless a link already chose, so it can be undone.
  const defs = allDefs.filter((d) => d.facets.length > 1 || d.value !== ALL);

  const active = defs.filter((d) => d.value !== ALL).length;
  const reset = () => {
    void setProtocol(null);
    void setHosting(null);
    void setPricing(null);
  };

  if (compact) {
    if (defs.length === 0) return null;
    // On a phone the three dropdowns are one: a Filters button whose popover
    // lists each facet as a section, the same rows as the dropdowns.
    return (
      <Popover>
        <PopoverTrigger asChild>
          <ToolbarButton aria-label={t("title")}>
            <ListFilter className={`${GLYPH} text-muted-foreground`} />
            {active > 0 && (
              <span className="rounded-full bg-primary px-1.5 text-[11px] leading-4 text-primary-foreground">
                {active}
              </span>
            )}
          </ToolbarButton>
        </PopoverTrigger>
        <PopoverContent
          align="end"
          className="max-h-[var(--radix-popover-content-available-height)] w-64 overflow-y-auto p-1.5"
          aria-label={t("title")}
        >
          {defs.map((d, index) => (
            <Fragment key={d.facet}>
              {index > 0 && <MenuSeparator />}
              <MenuSectionLabel>{d.label}</MenuSectionLabel>
              <MenuRow
                icon={d.allIcon}
                label={t("all")}
                selected={d.value === ALL}
                onClick={() => choose(d.facet)(ALL)}
              />
              {d.facets.map((f) => (
                <MenuRow
                  key={f.value}
                  icon={d.icon(f.value)}
                  label={
                    <CountedLabel name={d.name(f.value)} count={f.count} />
                  }
                  selected={d.value === f.value}
                  onClick={() => choose(d.facet)(f.value)}
                />
              ))}
            </Fragment>
          ))}
          {active > 0 && (
            <>
              <MenuSeparator />
              <MenuRow
                icon={<X className={GLYPH} />}
                label={t("clear")}
                onClick={reset}
              />
            </>
          )}
        </PopoverContent>
      </Popover>
    );
  }

  return (
    <>
      {/* Reset leads the filters, as on the audit log. */}
      {active > 0 && (
        <ToolbarButton
          aria-label={t("clear")}
          className="text-muted-foreground"
          onClick={reset}
        >
          <X className={GLYPH} />
          <span className="explore-filter-label max-sm:sr-only">
            {t("clear")}
          </span>
        </ToolbarButton>
      )}
      {defs.map((d) => (
        <ToolbarSelect
          key={d.facet}
          label={d.label}
          value={d.value}
          onChange={choose(d.facet)}
          // Icon-only when the subheader runs short (globals.css, explore-cq).
          labelClassName="explore-filter-label"
          groups={[
            [
              {
                value: ALL,
                label: t("all"),
                triggerLabel: d.label,
                icon: d.allIcon,
              },
            ],
            d.facets.map((f) => ({
              value: f.value,
              label: <CountedLabel name={d.name(f.value)} count={f.count} />,
              triggerLabel: d.name(f.value),
              icon: d.icon(f.value),
            })),
          ]}
        />
      ))}
    </>
  );
}
