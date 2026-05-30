"use client";

import { useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import { Filter, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface SkillsFiltersProps {
  sourceType: string;
  filesFilter: string;
  networkScope: string;
}

const SOURCE_TYPES = ["content", "github", "zip", "path"] as const;
const NETWORK_SCOPES = ["private", "ingress", "egress"] as const;

export default function SkillsFilters({
  sourceType,
  filesFilter,
  networkScope,
}: SkillsFiltersProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const t = useTranslations("SkillsPage.filters");
  const tSource = useTranslations("SkillsPage.source");

  const hasActiveFilters =
    Boolean(sourceType) || filesFilter !== "all" || Boolean(networkScope);

  const updateParam = (name: string, value: string, emptyValue = "all") => {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("page");

    if (value && value !== emptyValue) {
      params.set(name, value);
    } else {
      params.delete(name);
    }

    const query = params.toString();
    router.replace(query ? `/skills?${query}` : "/skills", { scroll: false });
  };

  const clearFilters = () => {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("page");
    params.delete("source_type");
    params.delete("files");
    params.delete("network_scope");

    const query = params.toString();
    router.replace(query ? `/skills?${query}` : "/skills", { scroll: false });
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select
        value={sourceType || "all"}
        onValueChange={(value) => updateParam("source_type", value)}
      >
        <SelectTrigger className="h-9 w-[150px]">
          <div className="flex items-center gap-2">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <SelectValue placeholder={t("source")} />
          </div>
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">{t("allSources")}</SelectItem>
          {SOURCE_TYPES.map((type) => (
            <SelectItem key={type} value={type}>
              {tSource(type)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select
        value={filesFilter}
        onValueChange={(value) => updateParam("files", value)}
      >
        <SelectTrigger className="h-9 w-[145px]">
          <SelectValue placeholder={t("files")} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">{t("allFiles")}</SelectItem>
          <SelectItem value="with_files">{t("withFiles")}</SelectItem>
          <SelectItem value="without_files">{t("withoutFiles")}</SelectItem>
        </SelectContent>
      </Select>

      <Select
        value={networkScope || "all"}
        onValueChange={(value) => updateParam("network_scope", value)}
      >
        <SelectTrigger className="h-9 w-[150px]">
          <SelectValue placeholder={t("scope")} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">{t("allScopes")}</SelectItem>
          {NETWORK_SCOPES.map((scope) => (
            <SelectItem key={scope} value={scope}>
              {t(`scopeValues.${scope}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {hasActiveFilters && (
        <Button
          variant="ghost"
          size="sm"
          className="h-9 gap-2"
          onClick={clearFilters}
        >
          <X className="h-4 w-4" />
          {t("clear")}
        </Button>
      )}
    </div>
  );
}
