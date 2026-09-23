"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { DollarSign } from "lucide-react";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  getWorkspaceSettingsAction,
  updateWorkspaceSettingsAction,
} from "@/lib/server-actions";

export default function WorkspaceConfigClient() {
  const t = useTranslations("WorkspacePage");

  const [currentCap, setCurrentCap] = useState<number | null | undefined>(undefined);
  const [capInput, setCapInput] = useState("");
  const [isLoadingCap, setIsLoadingCap] = useState(false);
  const [isSavingCap, setIsSavingCap] = useState(false);
  const [capStatus, setCapStatus] = useState<"idle" | "success" | "error">("idle");

  useEffect(() => {
    if (currentCap !== undefined) return;
    setIsLoadingCap(true);
    getWorkspaceSettingsAction().then(({ data }) => {
      if (data) {
        setCurrentCap(data.monthly_cap_usd);
        setCapInput(data.monthly_cap_usd != null ? String(data.monthly_cap_usd) : "");
      }
    }).finally(() => setIsLoadingCap(false));
  }, [currentCap]);

  const handleSaveCap = async () => {
    setIsSavingCap(true);
    setCapStatus("idle");
    const value = capInput.trim() === "" ? null : parseFloat(capInput);
    const { data, error } = await updateWorkspaceSettingsAction(value);
    if (error || !data) {
      setCapStatus("error");
    } else {
      setCurrentCap(data.monthly_cap_usd);
      setCapStatus("success");
    }
    setIsSavingCap(false);
  };

  return (
    <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-4">
      <div>
        <h3 className="text-sm font-semibold">{t("budget.title")}</h3>
        <p className="note mt-1">{t("budget.description")}</p>
      </div>

      <div className="grid gap-2">
        <FormLabel htmlFor="monthly-cap" icon={DollarSign}>
          {t("budget.label")}
        </FormLabel>
        <Input
          id="monthly-cap"
          type="number"
          step="0.01"
          min="0"
          value={capInput}
          onChange={(e) => {
            setCapInput(e.target.value);
            setCapStatus("idle");
          }}
          placeholder={t("budget.placeholder")}
          disabled={isLoadingCap || isSavingCap}
          className="max-w-xs"
        />
        <p className="text-xs text-muted-foreground">
          {isLoadingCap
            ? "..."
            : currentCap != null
            ? `${t("budget.current")}: $${currentCap.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
            : t("budget.noCap")}
        </p>
      </div>

      <div className="flex flex-col gap-1">
        <Button
          onClick={handleSaveCap}
          disabled={isSavingCap || isLoadingCap}
          size="sm"
          className="w-fit"
        >
          {isSavingCap ? t("budget.saving") : t("budget.save")}
        </Button>
        {capStatus === "success" && (
          <p className="text-xs text-green-600 dark:text-green-400">{t("budget.success")}</p>
        )}
        {capStatus === "error" && (
          <p className="text-xs text-destructive">{t("budget.error")}</p>
        )}
      </div>
    </div>
  );
}
