"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  listCatalogSuggestionsAction,
  type CatalogSuggestionItem,
} from "./catalog-suggestions-actions";

// A few catalog picks shown on an otherwise-empty type page, so users can add
// something in one click instead of facing a dead-end "Browse catalog" button.
// Clicking a card opens that item's detail in Explore (where Connect/Install
// lives). "Suggested" picks are curated in the catalog data
// (agentarea:suggested); otherwise we fall back to the first few items.

type CatalogType = "bundles" | "agents" | "skills" | "mcp_servers";

type RawSpec = Record<string, unknown>;

function iconOf(spec: RawSpec | undefined): string | null {
  if (!spec) return null;
  const raw = (spec.raw_spec as RawSpec | undefined) ?? spec;
  const icons = Array.isArray(raw.icons) ? (raw.icons as RawSpec[]) : [];
  const src = icons[0]?.src;
  return typeof src === "string" && src ? src : null;
}

export default function CatalogSuggestions({
  type,
  label = "Popular",
  max = 6,
}: {
  type: CatalogType;
  label?: string;
  max?: number;
}) {
  const [items, setItems] = useState<CatalogSuggestionItem[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const suggestions = await listCatalogSuggestionsAction(type, max);
        if (!cancelled) setItems(suggestions);
      } catch {
        if (!cancelled) setItems([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [type, max]);

  return (
    <div className="mx-auto mt-2 w-full max-w-2xl">
      {items.length > 0 && (
        <>
          <p className="mb-2 text-center text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            {label}
          </p>
          <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
            {items.map((it) => {
              const icon = iconOf(it.spec);
              return (
                <Link
                  key={it.id}
                  href={`/explore?type=${type}&item=${it.id}`}
                  className="flex items-center gap-2 rounded-lg border border-border/60 bg-white px-3 py-2 text-sm transition-shadow hover:shadow-sm dark:bg-zinc-900"
                >
                  {icon ? (
                    <Image
                      src={icon}
                      alt=""
                      width={20}
                      height={20}
                      className="h-5 w-5 shrink-0 rounded object-contain"
                    />
                  ) : (
                    <span className="h-5 w-5 shrink-0 rounded bg-muted" />
                  )}
                  <span className="truncate font-medium">{it.name}</span>
                </Link>
              );
            })}
          </div>
        </>
      )}
      <div className="flex justify-center">
        <Button asChild variant="outline">
          <Link href={`/explore?type=${type}`}>
            Browse the catalog
            <ArrowRight className="h-4 w-4" />
          </Link>
        </Button>
      </div>
    </div>
  );
}
