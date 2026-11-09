import { useLocale, useTranslations } from "next-intl";
import { Cpu, HardDrive, MemoryStick } from "lucide-react";
import type { RuntimeUsage } from "@/api/client";
import { BoardSectionHeader } from "@/components/board";
import { Stat, StatStrip } from "@/components/Overview/OverviewCard";
import { splitBytes } from "./usage-format";

/** What this workspace's runtime used this month and stores now; quantities, no price. */
export function RuntimeUsageStats({ usage }: { usage: RuntimeUsage }) {
  const t = useTranslations("BudgetsPage.runtime");
  const locale = useLocale();
  const num = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 });
  const stored = splitBytes(Number(usage.storage_gib));

  return (
    <div className="flex flex-col gap-3">
      <BoardSectionHeader
        icon={<Cpu />}
        color="hsl(var(--foreground))"
        title={t("title")}
        meta={t("hint")}
      />
      <StatStrip columns={3}>
        <Stat
          icon={<Cpu />}
          label={t("compute")}
          period={t("monthToDate")}
          value={num.format(Number(usage.cpu_core_hours))}
          unit={t("cpuUnit")}
          sub={t("computeSub")}
        />
        <Stat
          icon={<MemoryStick />}
          label={t("memory")}
          period={t("monthToDate")}
          value={num.format(Number(usage.memory_gib_hours))}
          unit={t("memoryUnit")}
          sub={t("memorySub")}
        />
        <Stat
          icon={<HardDrive />}
          label={t("storage")}
          period={t("now")}
          value={num.format(stored.value)}
          unit={stored.unit}
          sub={t("storageSub")}
        />
      </StatStrip>
    </div>
  );
}
