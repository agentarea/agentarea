"use client";

import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Layers } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

/** URL-param driven "group by" control for the Automation listing. */
export default function TriggersGroupSelect({
  currentGroup,
}: {
  currentGroup: string;
}) {
  const t = useTranslations("TriggersPage.group");
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const onChange = (value: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (value === "channel") params.delete("group");
    else params.set("group", value);
    const query = params.toString();
    router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  return (
    <Select value={currentGroup} onValueChange={onChange}>
      <SelectTrigger
        className={cn(
          "h-7 w-auto gap-1.5 rounded-md border border-border bg-background px-2 text-xs font-normal shadow-none focus:ring-0",
          currentGroup === "channel"
            ? "font-medium text-foreground"
            : "text-muted-foreground"
        )}
      >
        <Layers className="h-3.5 w-3.5 text-muted-foreground" />
        <SelectValue />
      </SelectTrigger>
      <SelectContent align="end">
        <SelectItem value="channel">{t("byChannel")}</SelectItem>
        <SelectItem value="none">{t("none")}</SelectItem>
      </SelectContent>
    </Select>
  );
}
