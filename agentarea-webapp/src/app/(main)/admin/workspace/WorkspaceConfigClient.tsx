"use client";

import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Download, FileUp, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { exportWorkspaceAction as exportWorkspace, importWorkspaceAction as importWorkspace } from "@/lib/server-actions";

export default function WorkspaceConfigClient() {
  const t = useTranslations("WorkspacePage");

  // Export state
  const [isExporting, setIsExporting] = useState(false);
  const [exportStatus, setExportStatus] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  // Import state
  const [yamlContent, setYamlContent] = useState("");
  const [skipMissing, setSkipMissing] = useState(false);
  const [overrideExisting, setOverrideExisting] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [importStatus, setImportStatus] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleExport = async () => {
    setIsExporting(true);
    setExportStatus(null);

    try {
      const { data, error } = await exportWorkspace();

      if (error || !data) {
        setExportStatus({
          type: "error",
          message: (error as any)?.detail?.[0]?.msg || t("export.error"),
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

      setExportStatus({ type: "success", message: t("export.success") });
    } finally {
      setIsExporting(false);
    }
  };

  const handleFileRead = (file: File) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const content = e.target?.result as string;
      setYamlContent(content);
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
      setImportStatus({ type: "error", message: t("import.error") });
      return;
    }

    setIsImporting(true);
    setImportStatus(null);

    try {
      const { data, error } = await importWorkspace({
        config: yamlContent,
        skip_missing_dependencies: skipMissing,
        override_existing: overrideExisting,
      });

      if (error) {
        setImportStatus({
          type: "error",
          message: (error as any)?.detail?.[0]?.msg || t("import.error"),
        });
        return;
      }

      const result = data as any;
      const successMsg = result?.imported_count
        ? `${t("import.success")} (${result.imported_count} items)`
        : t("import.success");

      setImportStatus({ type: "success", message: successMsg });
      setYamlContent("");
    } finally {
      setIsImporting(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      {/* Export Section */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Download className="h-4 w-4" />
            {t("export.title")}
          </CardTitle>
          <CardDescription>{t("export.description")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Button
            onClick={handleExport}
            disabled={isExporting}
            size="sm"
            className="gap-2"
          >
            <Download className="h-4 w-4" />
            {isExporting ? "Exporting..." : t("export.button")}
          </Button>

          {exportStatus && (
            <p
              className={`text-sm ${
                exportStatus.type === "success"
                  ? "text-green-600 dark:text-green-400"
                  : "text-red-600 dark:text-red-400"
              }`}
            >
              {exportStatus.message}
            </p>
          )}
        </CardContent>
      </Card>

      {/* Import Section */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Upload className="h-4 w-4" />
            {t("import.title")}
          </CardTitle>
          <CardDescription>{t("import.description")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Paste YAML */}
          <div className="space-y-1.5">
            <Label htmlFor="yaml-paste">{t("import.pasteLabel")}</Label>
            <Textarea
              id="yaml-paste"
              value={yamlContent}
              onChange={(e) => setYamlContent(e.target.value)}
              placeholder={t("import.pastePlaceholder")}
              className="min-h-[160px] font-mono text-xs"
            />
          </div>

          {/* File Upload */}
          <div className="space-y-1.5">
            <Label>{t("import.uploadLabel")}</Label>
            <div
              onClick={() => fileInputRef.current?.click()}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-8 text-center transition-colors ${
                isDragging
                  ? "border-primary bg-primary/5"
                  : "border-gray-200 hover:border-gray-300 hover:bg-gray-50 dark:border-gray-700 dark:hover:border-gray-600 dark:hover:bg-gray-800/50"
              }`}
            >
              <FileUp className="h-8 w-8 text-gray-400" />
              <div className="text-sm text-gray-600 dark:text-gray-400">
                <span>{t("import.dragDrop")}</span>{" "}
                <span className="font-medium text-primary">
                  {t("import.browse")}
                </span>
              </div>
              <p className="text-xs text-gray-400">.yaml, .yml</p>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".yaml,.yml"
              className="hidden"
              onChange={handleFileChange}
            />
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
                <Label htmlFor="skip-missing" className="cursor-pointer">
                  {t("import.skipMissing")}
                </Label>
                <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
                  {t("import.skipMissingDescription")}
                </p>
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
                <Label htmlFor="override-existing" className="cursor-pointer">
                  {t("import.overrideExisting")}
                </Label>
                <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
                  {t("import.overrideExistingDescription")}
                </p>
              </div>
            </div>
          </div>

          <Button
            onClick={handleImport}
            disabled={isImporting || !yamlContent.trim()}
            size="sm"
            className="gap-2"
          >
            <Upload className="h-4 w-4" />
            {isImporting ? "Importing..." : t("import.button")}
          </Button>

          {importStatus && (
            <p
              className={`text-sm ${
                importStatus.type === "success"
                  ? "text-green-600 dark:text-green-400"
                  : "text-red-600 dark:text-red-400"
              }`}
            >
              {importStatus.message}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
