"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import { FileText, Filter, Globe, X } from "lucide-react";
import { cn } from "@/lib/utils";
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

interface FilterSelectProps {
  icon: ReactNode;
  value: string;
  active: boolean;
  placeholder: string;
  onValueChange: (value: string) => void;
  children: ReactNode;
}

function FilterSelect({
  icon,
  value,
  active,
  placeholder,
  onValueChange,
  children,
}: FilterSelectProps) {
  return (
    <Select value={value} onValueChange={onValueChange}>
      <SelectTrigger
        className={cn(
          "h-8 w-auto gap-1.5 rounded-md border-0 bg-transparent px-2 text-xs font-normal shadow-none transition-colors dark:bg-transparent",
          "hover:bg-muted focus:ring-0 data-[state=open]:bg-muted dark:hover:bg-muted",
          active ? "font-medium text-foreground" : "text-muted-foreground"
        )}
      >
        <span className="flex items-center gap-1.5">
          {icon}
          <SelectValue placeholder={placeholder} />
        </span>
      </SelectTrigger>
      <SelectContent>{children}</SelectContent>
    </Select>
  );
}

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
    params.delete("source_type");
    params.delete("files");
    params.delete("network_scope");

    const query = params.toString();
    router.replace(query ? `/skills?${query}` : "/skills", { scroll: false });
  };

  return (
    <div className="flex items-center gap-0.5">
      <FilterSelect
        icon={<Filter className="h-3.5 w-3.5" />}
        value={sourceType || "all"}
        active={Boolean(sourceType)}
        placeholder={t("source")}
        onValueChange={(value) => updateParam("source_type", value)}
      >
        <SelectItem value="all">{t("allSources")}</SelectItem>
        {SOURCE_TYPES.map((type) => (
          <SelectItem key={type} value={type}>
            {tSource(type)}
          </SelectItem>
        ))}
      </FilterSelect>

      <FilterSelect
        icon={<FileText className="h-3.5 w-3.5" />}
        value={filesFilter}
        active={filesFilter !== "all"}
        placeholder={t("files")}
        onValueChange={(value) => updateParam("files", value)}
      >
        <SelectItem value="all">{t("allFiles")}</SelectItem>
        <SelectItem value="with_files">{t("withFiles")}</SelectItem>
        <SelectItem value="without_files">{t("withoutFiles")}</SelectItem>
      </FilterSelect>

      <FilterSelect
        icon={<Globe className="h-3.5 w-3.5" />}
        value={networkScope || "all"}
        active={Boolean(networkScope)}
        placeholder={t("scope")}
        onValueChange={(value) => updateParam("network_scope", value)}
      >
        <SelectItem value="all">{t("allScopes")}</SelectItem>
        {NETWORK_SCOPES.map((scope) => (
          <SelectItem key={scope} value={scope}>
            {t(`scopeValues.${scope}`)}
          </SelectItem>
        ))}
      </FilterSelect>

      {hasActiveFilters && (
        <Button
          variant="ghost"
          size="sm"
          className="h-8 gap-1 px-2 text-xs text-muted-foreground hover:text-foreground"
          onClick={clearFilters}
        >
          <X className="h-3.5 w-3.5" />
          {t("clear")}
        </Button>
      )}
    </div>
  );
}
