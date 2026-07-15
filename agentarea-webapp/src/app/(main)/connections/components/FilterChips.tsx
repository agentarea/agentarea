"use client";

import { useCallback } from "react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import {
  MCPServerCategory,
  MCPConnectionType,
  CONNECTION_TYPE_CONFIG,
  getCategoryColorClasses,
} from "../utils";

const ALL_CATEGORIES: MCPServerCategory[] = [
  "AI",
  "Data",
  "Dev",
  "Web",
  "Files",
  "Messaging",
  "Tools",
];

const ALL_TYPES: MCPConnectionType[] = ["docker", "command", "url"];

export function FilterChips() {
  const t = useTranslations("MCPServersPage.filters");
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const activeType = searchParams.get("type") || "";
  const activeCategory = searchParams.get("category") || "";

  const updateParam = useCallback(
    (key: string, value: string) => {
      const params = new URLSearchParams(searchParams.toString());
      if (value && params.get(key) !== value) {
        params.set(key, value);
      } else {
        params.delete(key);
      }
      router.replace(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [router, pathname, searchParams]
  );

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs font-medium text-muted-foreground mr-1">
        {t("type")}:
      </span>
      {ALL_TYPES.map((type) => {
        const config = CONNECTION_TYPE_CONFIG[type];
        const isActive = activeType === type;
        return (
          <Badge
            key={type}
            variant="outline"
            className={`cursor-pointer select-none text-xs transition-colors ${
              isActive
                ? config.color
                : "hover:bg-muted"
            }`}
            onClick={() => updateParam("type", type)}
          >
            {config.label}
          </Badge>
        );
      })}

      <span className="text-muted-foreground/40 mx-1">|</span>

      <span className="text-xs font-medium text-muted-foreground mr-1">
        {t("category")}:
      </span>
      {ALL_CATEGORIES.map((cat) => {
        const isActive = activeCategory === cat;
        return (
          <Badge
            key={cat}
            variant="outline"
            className={`cursor-pointer select-none text-xs transition-colors ${
              isActive
                ? getCategoryColorClasses(cat)
                : "hover:bg-muted"
            }`}
            onClick={() => updateParam("category", cat)}
          >
            {cat}
          </Badge>
        );
      })}
    </div>
  );
}
