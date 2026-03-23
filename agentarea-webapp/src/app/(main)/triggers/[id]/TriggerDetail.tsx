"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { formatDistanceToNow } from "date-fns";
import {
  Clock,
  Webhook,
  Bot,
  Settings,
  Pencil,
  Power,
  PowerOff,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import DeleteButton from "@/components/DeleteButton";
import { useToast } from "@/hooks/use-toast";
import {
  enableTrigger,
  disableTrigger,
  deleteTrigger,
} from "@/lib/browser-api";

interface TriggerDetailProps {
  trigger: any;
  agentName: string;
}

export default function TriggerDetail({
  trigger,
  agentName,
}: TriggerDetailProps) {
  const t = useTranslations("TriggersPage.detail");
  const tType = useTranslations("TriggersPage.type");
  const tStatus = useTranslations("TriggersPage.status");
  const tError = useTranslations("TriggersPage.error");
  const tSuccess = useTranslations("TriggersPage.success");
  const { toast } = useToast();
  const router = useRouter();
  const [isActive, setIsActive] = useState(trigger.is_active);
  const [isToggling, setIsToggling] = useState(false);
  const isCron = trigger.trigger_type === "cron";

  const handleToggle = async () => {
    setIsToggling(true);
    try {
      const action = isActive ? disableTrigger : enableTrigger;
      const { error } = await action(trigger.id);
      if (error) {
        toast({
          title: isActive ? tError("disableFailed") : tError("enableFailed"),
          variant: "destructive",
        });
      } else {
        setIsActive(!isActive);
        toast({
          title: isActive ? tSuccess("disabled") : tSuccess("enabled"),
          variant: "success",
        });
        router.refresh();
      }
    } finally {
      setIsToggling(false);
    }
  };

  return (
    <div className="space-y-6 p-6">
      {/* Actions bar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Badge variant={isActive ? "default" : "secondary"} className="text-sm">
            {isActive ? tStatus("active") : tStatus("inactive")}
          </Badge>
          <Badge variant="outline" className="gap-1 text-sm">
            {isCron ? <Clock className="h-3 w-3" /> : <Webhook className="h-3 w-3" />}
            {isCron ? tType("cron") : tType("webhook")}
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleToggle}
            disabled={isToggling}
          >
            {isActive ? (
              <>
                <PowerOff className="mr-2 h-4 w-4" />
                {t("disable")}
              </>
            ) : (
              <>
                <Power className="mr-2 h-4 w-4" />
                {t("enable")}
              </>
            )}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => router.push(`/triggers/${trigger.id}/edit`)}
          >
            <Pencil className="mr-2 h-4 w-4" />
            {t("edit")}
          </Button>
          <DeleteButton
            itemId={trigger.id}
            itemName={trigger.name}
            onDelete={deleteTrigger}
            redirectPath="/triggers"
            title={t("delete")}
            description={t("deleteDescription")}
            successMessage={tSuccess("deleted")}
            size="sm"
          />
        </div>
      </div>

      {/* Configuration Card */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Settings className="h-4 w-4" />
            {t("configuration")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <dt className="text-sm font-medium text-muted-foreground">
                {t("triggerType")}
              </dt>
              <dd className="mt-1 flex items-center gap-1.5">
                {isCron ? <Clock className="h-4 w-4" /> : <Webhook className="h-4 w-4" />}
                {isCron ? tType("cron") : tType("webhook")}
              </dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-muted-foreground">
                {t("agent")}
              </dt>
              <dd className="mt-1 flex items-center gap-1.5">
                <Bot className="h-4 w-4" />
                {agentName}
              </dd>
            </div>
            {isCron && trigger.config?.cron_expression && (
              <div>
                <dt className="text-sm font-medium text-muted-foreground">
                  {t("cronExpression")}
                </dt>
                <dd className="mt-1 font-mono text-sm">
                  {trigger.config.cron_expression}
                  {trigger.config.timezone && (
                    <span className="ml-2 text-muted-foreground">
                      ({trigger.config.timezone})
                    </span>
                  )}
                </dd>
              </div>
            )}
            {!isCron && trigger.webhook_type && (
              <div>
                <dt className="text-sm font-medium text-muted-foreground">
                  Webhook Type
                </dt>
                <dd className="mt-1 capitalize">
                  {trigger.webhook_type}
                </dd>
              </div>
            )}
            {trigger.event_types && trigger.event_types.length > 0 && (
              <div className="sm:col-span-2">
                <dt className="text-sm font-medium text-muted-foreground">
                  Event Filters
                </dt>
                <dd className="mt-1.5 flex flex-wrap gap-1.5">
                  {trigger.event_types.map((event: string) => (
                    <Badge key={event} variant="outline" className="text-xs font-mono">
                      {event}
                    </Badge>
                  ))}
                </dd>
              </div>
            )}
            <div>
              <dt className="text-sm font-medium text-muted-foreground">
                {t("nextRun")}
              </dt>
              <dd className="mt-1">
                {trigger.next_run_at
                  ? formatDistanceToNow(new Date(trigger.next_run_at), {
                      addSuffix: true,
                    })
                  : "-"}
              </dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-muted-foreground">
                {t("lastRun")}
              </dt>
              <dd className="mt-1">
                {trigger.last_run_at
                  ? formatDistanceToNow(new Date(trigger.last_run_at), {
                      addSuffix: true,
                    })
                  : "-"}
              </dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      {/* Task Parameters Card */}
      {trigger.task_parameters &&
        Object.keys(trigger.task_parameters).length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Task Parameters</CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="overflow-auto rounded-md bg-muted p-4 text-sm font-mono">
                {JSON.stringify(trigger.task_parameters, null, 2)}
              </pre>
            </CardContent>
          </Card>
        )}
    </div>
  );
}
