"use client";

import { useTranslations } from "next-intl";
import { CheckCircle2, FileText, Loader2 } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface TaskResultsCardProps {
  task: {
    result?: Record<string, unknown>;
  };
  taskStatus?: {
    session_id?: string;
  } | null;
  isActive: boolean;
}

export default function TaskResultsCard({
  task,
  taskStatus,
  isActive,
}: TaskResultsCardProps) {
  const t = useTranslations("TaskResultsCard");

  return (
    <Card className="shadow-sm">
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-green-100 dark:bg-green-900/30">
            <FileText className="h-4 w-4 text-green-600" />
          </div>
          <div>
            <CardTitle className="text-base">{t("title")}</CardTitle>
            <CardDescription className="text-xs">
              {t("description")}
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {task.result ? (
          <div className="space-y-2">
            <div className="rounded-lg border border-green-200 bg-green-50 p-3 dark:border-green-800 dark:bg-green-900/20">
              <div className="mb-2 flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-green-600" />
                <h4 className="text-sm font-medium text-green-900 dark:text-green-100">
                  {t("result")}
                </h4>
              </div>
              <div className="max-h-32 overflow-y-auto rounded bg-white p-2 dark:bg-gray-800">
                <pre className="whitespace-pre-wrap text-xs text-gray-900 dark:text-gray-100">
                  {JSON.stringify(task.result, null, 2)}
                </pre>
              </div>
            </div>
          </div>
        ) : (
          <div className="py-6 text-center">
            <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-full bg-gray-100 dark:bg-gray-800">
              {isActive ? (
                <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
              ) : (
                <FileText className="h-6 w-6 text-gray-400" />
              )}
            </div>
            <h3 className="mb-1 text-sm font-semibold text-gray-900 dark:text-gray-100">
              {isActive ? t("taskRunning") : t("noResults")}
            </h3>
            <p className="text-xs text-gray-600 dark:text-gray-400">
              {isActive ? t("resultsWillAppear") : t("noResultsProduced")}
            </p>
          </div>
        )}

        {taskStatus?.session_id && (
          <div className="mt-3 rounded border border-sky-200 bg-sky-50 p-2 dark:border-sky-800 dark:bg-sky-900/20">
            <p className="mb-0.5 text-xs text-sky-600 dark:text-sky-400">
              {t("sessionId")}
            </p>
            <code className="break-all font-mono text-xs text-sky-900 dark:text-sky-100">
              {taskStatus.session_id}
            </code>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
