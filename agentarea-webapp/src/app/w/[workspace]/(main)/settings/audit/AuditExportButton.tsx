"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { exportAuditLogs } from "./actions";
import { auditEventsToCsv } from "./auditCsv";
import { auditQuery, parseAuditFilters } from "./auditFilters";

/** Downloads every event matching the filters in the URL as CSV. */
export default function AuditExportButton() {
  const t = useTranslations("AuditLogPage.export");
  const searchParams = useSearchParams();
  const [notice, setNotice] = useState<{ text: string; failed: boolean }>();
  const [exporting, startExport] = useTransition();

  const exportCsv = () => {
    setNotice(undefined);
    startExport(async () => {
      const query = auditQuery(parseAuditFilters(searchParams), Date.now());
      const { data, error } = await exportAuditLogs(query);
      if (!data) {
        setNotice({ text: `${t("failed")}: ${error}`, failed: true });
        return;
      }
      const url = URL.createObjectURL(
        new Blob([auditEventsToCsv(data.events)], {
          type: "text/csv;charset=utf-8",
        })
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = `audit-log-${new Date().toISOString().slice(0, 10)}.csv`;
      link.click();
      URL.revokeObjectURL(url);
      if (data.truncated) {
        setNotice({
          text: t("truncated", { count: data.events.length }),
          failed: false,
        });
      }
    });
  };

  return (
    <div className="flex min-w-0 items-center gap-3">
      {notice && (
        <span
          role={notice.failed ? "alert" : "status"}
          title={notice.text}
          className={cn(
            "max-w-[40vw] truncate text-xs sm:max-w-80",
            notice.failed ? "text-destructive" : "text-muted-foreground"
          )}
        >
          {notice.text}
        </span>
      )}
      <Button
        variant="outline"
        size="xs"
        className="shrink-0"
        isLoading={exporting}
        onClick={exportCsv}
      >
        {!exporting && <Download />}
        {exporting ? t("working") : t("button")}
      </Button>
    </div>
  );
}
