import { getTranslations } from "next-intl/server";
import { getTriggerMetrics } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CheckCircle, Clock, Hash } from "lucide-react";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function TriggerMetricsPage({ params }: Props) {
  const { id } = await params;
  const t = await getTranslations("TriggersPage.detail");

  const { data, error } = await getTriggerMetrics(id);

  if (error || !data) {
    return (
      <div className="flex h-64 items-center justify-center text-destructive">
        Failed to load metrics
      </div>
    );
  }

  const metrics = data as any;

  return (
    <div className="p-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {t("totalExecutions")}
            </CardTitle>
            <Hash className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {metrics.total_executions ?? 0}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {t("successRate")}
            </CardTitle>
            <CheckCircle className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {metrics.success_rate != null
                ? `${(metrics.success_rate * 100).toFixed(1)}%`
                : "N/A"}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {t("avgExecutionTime")}
            </CardTitle>
            <Clock className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {metrics.avg_execution_time_ms != null
                ? `${(metrics.avg_execution_time_ms / 1000).toFixed(2)}s`
                : "N/A"}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
