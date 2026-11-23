"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import {
  CircleDollarSign,
  Cloud,
  Gift,
  Globe,
  KeyRound,
  Plug,
  Server,
  Wallet,
  X,
} from "lucide-react";
import { parseAsString, parseAsStringLiteral, useQueryState } from "nuqs";
import SearchInput from "@/components/SearchInput";
import ToolbarSelect from "@/components/ToolbarSelect";
import { ToolbarButton } from "@/components/ui/toolbar";
import {
  ALL,
  PROTOCOL_LABELS,
  TYPE_KEYS,
  type CatalogType,
} from "./catalog-data";
import type { CategoryFacet } from "./catalog-paging";
import { useExplorePending } from "./CatalogGallery";

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
}: {
  initialType: CatalogType;
  protocols: CategoryFacet[];
  hostings: CategoryFacet[];
  pricings: CategoryFacet[];
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

  const select = (
    facet: Facet,
    label: string,
    allIcon: ReactNode,
    facets: CategoryFacet[],
    value: string,
    name: (v: string) => string,
    icon: (v: string) => ReactNode
  ) =>
    // Nothing to choose between — unless a link already chose, so it can be undone.
    (facets.length > 1 || value !== ALL) && (
      <ToolbarSelect
        label={label}
        value={value}
        onChange={choose(facet)}
        groups={[
          [{ value: ALL, label: t("all"), triggerLabel: label, icon: allIcon }],
          facets.map((f) => ({
            value: f.value,
            label: <CountedLabel name={name(f.value)} count={f.count} />,
            triggerLabel: name(f.value),
            icon: icon(f.value),
          })),
        ]}
      />
    );

  const anyFilter = protocol !== ALL || hosting !== ALL || pricing !== ALL;

  return (
    <>
      {/* Reset leads the filters, as on the audit log. */}
      {anyFilter && (
        <ToolbarButton
          aria-label={t("clear")}
          className="text-muted-foreground"
          onClick={() => {
            void setProtocol(null);
            void setHosting(null);
            void setPricing(null);
          }}
        >
          <X className={GLYPH} />
          <span className="max-sm:sr-only">{t("clear")}</span>
        </ToolbarButton>
      )}
      {select(
        "protocol",
        t("protocol"),
        <Plug className={`${GLYPH} text-muted-foreground`} />,
        protocols,
        protocol,
        (v) => PROTOCOL_LABELS[v as keyof typeof PROTOCOL_LABELS] ?? v,
        (v) => (v === "mcp" ? <McpGlyph /> : <Globe className={GLYPH} />)
      )}
      {select(
        "hosting",
        t("hosting"),
        <Server className={`${GLYPH} text-muted-foreground`} />,
        hostings,
        hosting,
        (v) => (v === "vendor" || v === "agentarea" ? t(`hostings.${v}`) : v),
        (v) =>
          v === "vendor" ? (
            <Cloud className={GLYPH} />
          ) : (
            <Server className={GLYPH} />
          )
      )}
      {select(
        "pricing",
        tPricing("facet"),
        <Wallet className={`${GLYPH} text-muted-foreground`} />,
        pricings,
        pricing,
        (v) =>
          v === "paid" || v === "own_key" || v === "free"
            ? tPricing(`kinds.${v}`)
            : v,
        (v) =>
          v === "paid" ? (
            <CircleDollarSign className={GLYPH} />
          ) : v === "own_key" ? (
            <KeyRound className={GLYPH} />
          ) : (
            <Gift className={GLYPH} />
          )
      )}
    </>
  );
}
