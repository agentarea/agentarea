"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { DollarSign, Download, FileUp, Upload } from "lucide-react";
import { ChatWelcome } from "@/components/Chat/componets/ChatWelcome";
import FormLabel from "@/components/FormLabel/FormLabel";
import { AnimatedTabs } from "@/components/ui/animated-tabs";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import {
  exportWorkspaceAction as exportWorkspace,
  importWorkspaceAction as importWorkspace,
  getWorkspaceSettingsAction,
  updateWorkspaceSettingsAction,
} from "@/lib/server-actions";
import { cn } from "@/lib/utils";

export default function WorkspaceConfigClient() {
  const t = useTranslations("WorkspacePage");
  const { toast } = useToast();

  const [activeTab, setActiveTab] = useState("export");

  const [isExporting, setIsExporting] = useState(false);

  const [yamlContent, setYamlContent] = useState("");
  const [skipMissing, setSkipMissing] = useState(false);
  const [overrideExisting, setOverrideExisting] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [uploadedFileName, setUploadedFileName] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const [currentCap, setCurrentCap] = useState<number | null | undefined>(undefined);
  const [capInput, setCapInput] = useState("");
  const [isLoadingCap, setIsLoadingCap] = useState(false);
  const [isSavingCap, setIsSavingCap] = useState(false);
  const [capStatus, setCapStatus] = useState<"idle" | "success" | "error">("idle");

  useEffect(() => {
    if (activeTab !== "budget") return;
    if (currentCap !== undefined) return;
    setIsLoadingCap(true);
    getWorkspaceSettingsAction().then(({ data }) => {
      if (data) {
        setCurrentCap(data.monthly_cap_usd);
        setCapInput(data.monthly_cap_usd != null ? String(data.monthly_cap_usd) : "");
      }
    }).finally(() => setIsLoadingCap(false));
  }, [activeTab, currentCap]);

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

  const handleExport = async () => {
    setIsExporting(true);

    try {
      const { data, error } = await exportWorkspace();

      if (error || !data) {
        toast({
          title: t("export.error"),
          variant: "destructive",
        });
        return;
      }

      const yaml =
        typeof data === "string" ? data : JSON.stringify(data, null, 2);
      const blob = new Blob([yaml], { type: "text/yaml" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "workspace-config.yaml";
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);

      toast({
        title: t("export.success"),
        variant: "success",
      });
    } finally {
      setIsExporting(false);
    }
  };

  const handleFileRead = (file: File) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const content = e.target?.result as string;
      setYamlContent(content);
      setUploadedFileName(file.name);
    };
    reader.readAsText(file);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      handleFileRead(file);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) {
      handleFileRead(file);
    }
  };

  const handleImport = async () => {
    if (!yamlContent.trim()) {
      toast({
        title: t("import.error"),
        variant: "destructive",
      });
      return;
    }

    setIsImporting(true);

    try {
      const { data, error } = await importWorkspace({
        config: yamlContent,
        skip_missing_dependencies: skipMissing,
        override_existing: overrideExisting,
      });

      if (error) {
        toast({
          title: (error as any)?.detail?.[0]?.msg || t("import.error"),
          variant: "destructive",
        });
        return;
      }

      const result = data as any;
      const successMsg = result?.imported_count
        ? `${t("import.success")} (${result.imported_count} items)`
        : t("import.success");

      toast({
        title: successMsg,
        variant: "success",
      });
      setYamlContent("");
      setUploadedFileName(null);
    } finally {
      setIsImporting(false);
    }
  };

  return (
    <div className="form-content lg:max-w-xl lg:mx-auto">
      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
        <div className="mb-6">
          <AnimatedTabs
            activeTab={activeTab}
            onChange={setActiveTab}
            tabs={[
              {
                value: "export",
                label: t("export.tabLabel"),
                icon: <Download className="h-4 w-4" />,
              },
              {
                value: "import",
                label: t("import.tabLabel"),
                icon: <Upload className="h-4 w-4" />,
              },
              {
                value: "budget",
                label: t("budget.tabLabel"),
                icon: <DollarSign className="h-4 w-4" />,
              },
            ]}
          />
        </div>

        <TabsContent value="export" className="space-y-4">
          <div className="flex flex-col items-center justify-center py-8">
            <ChatWelcome
              icon={Download}
              title={t("export.title")}
              subtitle={t("export.description")}
              variant="neutral"
              size="md"
              animate={false}
              subtitleClassName="font-extralight"
              iconWrapperClassName="bg-primary/5 dark:bg-primary/10"
              iconColorClassName="text-primary dark:text-primary"
            />
            <Button
              onClick={handleExport}
              disabled={isExporting}
              size="sm"
              className="gap-2 mt-4"
            >
              <Download className="h-4 w-4" />
              {isExporting ? t("export.exporting") : t("export.button")}
            </Button>
          </div>
        </TabsContent>

        <TabsContent value="import" className="space-y-4">
          <div className="grid gap-4">
            {/* Paste YAML */}
            <div className="grid gap-2">
              <FormLabel htmlFor="yaml-paste" icon={FileUp}>
                {t("import.pasteLabel")}
              </FormLabel>
              <Textarea
                id="yaml-paste"
                value={yamlContent}
                onChange={(e) => setYamlContent(e.target.value)}
                placeholder={t("import.pastePlaceholder")}
                className="min-h-[160px] font-mono text-sm"
              />
            </div>

            {/* File Upload Dropzone */}
            <div
              className={cn(
                "border-2 border-dashed rounded-lg p-8 text-center transition-colors",
                isDragging
                  ? "border-primary bg-primary/5"
                  : "border-muted-foreground/25 hover:border-primary/50"
              )}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
            >
              <div className="flex flex-col items-center justify-center gap-2">
                <FileUp className="h-8 w-8 text-muted-foreground" />
                <div className="text-sm text-muted-foreground">
                  <span className="font-semibold">{t("import.dragDrop")}</span>{" "}
                  <label
                    htmlFor="file-upload"
                    className="text-primary hover:underline cursor-pointer"
                  >
                    {t("import.browse")}
                  </label>
                  <input
                    id="file-upload"
                    type="file"
                    accept=".yaml,.yml"
                    className="hidden"
                    onChange={handleFileChange}
                  />
                </div>
                {uploadedFileName && (
                  <div className="mt-2 flex items-center gap-2 text-sm font-medium bg-secondary px-3 py-1 rounded-full">
                    <FileUp className="h-4 w-4" />
                    {uploadedFileName}
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-4 w-4 ml-1 rounded-full hover:bg-destructive/20"
                      onClick={(e) => {
                        e.preventDefault();
                        setUploadedFileName(null);
                        setYamlContent("");
                      }}
                    >
                      ×
                    </Button>
                  </div>
                )}
              </div>
            </div>

            {/* Options */}
            <div className="space-y-3">
              <div className="flex items-start gap-3">
                <Checkbox
                  id="skip-missing"
                  checked={skipMissing}
                  onCheckedChange={(checked) =>
                    setSkipMissing(checked === true)
                  }
                  className="mt-0.5"
                />
                <div>
                  <label
                    htmlFor="skip-missing"
                    className="cursor-pointer text-sm font-medium text-zinc-700 dark:text-zinc-200"
                  >
                    {t("import.skipMissing")}
                  </label>
                  <p className="note">{t("import.skipMissingDescription")}</p>
                </div>
              </div>

              <div className="flex items-start gap-3">
                <Checkbox
                  id="override-existing"
                  checked={overrideExisting}
                  onCheckedChange={(checked) =>
                    setOverrideExisting(checked === true)
                  }
                  className="mt-0.5"
                />
                <div>
                  <label
                    htmlFor="override-existing"
                    className="cursor-pointer text-sm font-medium text-zinc-700 dark:text-zinc-200"
                  >
                    {t("import.overrideExisting")}
                  </label>
                  <p className="note">
                    {t("import.overrideExistingDescription")}
                  </p>
                </div>
              </div>
            </div>

            {/* Import Button */}
            <Button
              onClick={handleImport}
              disabled={isImporting || !yamlContent.trim()}
              size="sm"
              className="gap-2 w-fit"
            >
              <Upload className="h-4 w-4" />
              {isImporting ? t("import.importing") : t("import.button")}
            </Button>
          </div>
        </TabsContent>
        <TabsContent value="budget" className="space-y-4">
          <div className="grid gap-4">
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
        </TabsContent>
      </Tabs>
    </div>
  );
}
