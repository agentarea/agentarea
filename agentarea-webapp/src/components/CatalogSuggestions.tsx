"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EntityIcon, type EntityKind } from "@/lib/entity-icons";
import {
  listCatalogSuggestionsAction,
  type CatalogSuggestionItem,
} from "./catalog-suggestions-actions";

// A few catalog picks shown on an otherwise-empty type page, so users can add
// something in one click instead of facing a dead-end "Browse catalog" button.
// Clicking a card opens that item's detail in Explore (where Connect/Install
// lives). Skills come from the small curated registry and are ranked by the
// source repository's popularity. Other types use the catalog's featured sort.

type CatalogType = "bundles" | "agents" | "skills" | "mcp_servers";

function entityKind(type: CatalogType): EntityKind {
  if (type === "agents") return "agent";
  if (type === "mcp_servers") return "mcp";
  return "skill";
}

export default function CatalogSuggestions({
  type,
  label,
  max = 6,
}: {
  type: CatalogType;
  label?: string;
  max?: number;
}) {
  const [items, setItems] = useState<CatalogSuggestionItem[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const heading =
    label ?? (type === "skills" ? "Popular skills" : "Recommended");

  useEffect(() => {
    let cancelled = false;
    setState("loading");
    (async () => {
      try {
        const suggestions = await listCatalogSuggestionsAction(type, max);
        if (!cancelled) {
          setItems(suggestions);
          setState("ready");
        }
      } catch {
        if (!cancelled) {
          setItems([]);
          setState("error");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [type, max]);

  return (
    <div className="mx-auto mt-2 w-full max-w-3xl">
      <div className="min-h-[174px]">
        <p className="mb-2 text-center text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          {heading}
        </p>
        {state === "loading" ? (
          <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
            {Array.from({ length: max }, (_, index) => (
              <div
                key={index}
                className="flex min-h-[70px] gap-2.5 rounded-lg border border-border/40 px-3 py-2.5"
              >
                <Skeleton className="h-7 w-7 shrink-0" />
                <div className="min-w-0 flex-1 space-y-2">
                  <Skeleton className="h-3.5 w-3/4" />
                  <Skeleton className="h-3 w-full" />
                </div>
              </div>
            ))}
          </div>
        ) : items.length > 0 ? (
          <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
            {items.map((it) => {
              return (
                <Link
                  key={it.id}
                  href={`/explore?type=${type}&item=${it.id}`}
                  className="flex min-h-[70px] items-start gap-2.5 rounded-lg border border-border/60 bg-white px-3 py-2.5 text-sm transition-all hover:-translate-y-px hover:border-border hover:shadow-sm dark:bg-zinc-900"
                >
                  {it.iconUrl ? (
                    <Image
                      src={it.iconUrl}
                      alt=""
                      width={28}
                      height={28}
                      className="h-7 w-7 shrink-0 rounded-md object-contain"
                    />
                  ) : (
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                      <EntityIcon
                        kind={entityKind(type)}
                        className="h-3.5 w-3.5"
                      />
                    </span>
                  )}
                  <span className="min-w-0">
                    <span className="block truncate font-medium">
                      {it.title}
                    </span>
                    {it.description && (
                      <span className="mt-0.5 line-clamp-2 block text-[11px] leading-4 text-muted-foreground">
                        {it.description}
                      </span>
                    )}
                    {(it.source || it.popularityLabel) && (
                      <span className="mt-1 block truncate text-[10px] text-muted-foreground/80">
                        {[it.source, it.popularityLabel]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    )}
                  </span>
                </Link>
              );
            })}
          </div>
        ) : (
          <p className="flex min-h-[132px] items-center justify-center text-xs text-muted-foreground">
            {state === "error"
              ? "Catalog recommendations are unavailable right now."
              : "No catalog recommendations yet."}
          </p>
        )}
      </div>
      <div className="flex justify-center">
        <Button asChild variant="outline">
          <Link href={`/explore?type=${type}`}>
            Browse the catalog
            <ArrowRight />
          </Link>
        </Button>
      </div>
    </div>
  );
}
