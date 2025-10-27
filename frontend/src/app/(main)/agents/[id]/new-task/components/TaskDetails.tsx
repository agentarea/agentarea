import { useTranslations } from "next-intl";
import { Clock, DollarSign, TrendingUp } from "lucide-react";
import { Card } from "@/components/ui/card";
import ModelBadge from "@/components/ui/model-badge";
import { cn } from "@/lib/utils";
import { Agent } from "@/types/agent";
import Timer from "./Timer";
import ToolsDisplay from "./ToolsDisplay";

interface Props {
  agent: Agent;
  isTaskRunning?: boolean;
  isTaskActive?: boolean;
}

export default function TaskDetails({
  agent,
  isTaskRunning = false,
  isTaskActive = false,
}: Props) {
  const t = useTranslations("AgentsPage.descriptionPage");
  return (
    <Card className="flex h-full flex-col gap-3 overflow-auto rounded-none border-b-0 border-r-0 border-t-0 md:min-w-[250px] md:max-w-[250px] lg:min-w-[300px] lg:max-w-[300px] cursor-auto">
      <h3 className="">{t("agentDetails")}</h3>
      <div className="flex flex-col space-y-2">
        <div className="flex flex-row items-center gap-2">
          <p className="text-xs">{t("model")}:</p>
          <ModelBadge
            providerName={agent.model_info?.provider_name}
            modelDisplayName={agent.model_info?.model_display_name}
            configName={agent.model_info?.config_name}
          />
        </div>
        <div className="flex flex-row items-center gap-2">
          <p className="text-xs">{t("tools")}:</p>
          <ToolsDisplay agent={agent} />
        </div>
        {agent.description && (
          <div className="flex flex-1 flex-row items-start gap-2">
            <p className="mt-0.5 text-xs">{t("description")}:</p>
            <p className="line-clamp-2 min-w-0 flex-1 overflow-hidden text-xs text-gray-500">
              {agent.description}
            </p>
          </div>
        )}
      </div>

      {isTaskActive && (
        <>
          <h3 className="mt-5">{t("taskDetails")}</h3>
          <div className="flex flex-col space-y-2">
            <div className="flex flex-row items-baseline gap-2">
              <div
                className={cn(
                  "flex flex-row items-center gap-1 text-xs text-primary"
                )}
              >
                <Clock className="mt-0.5 h-3 w-3" /> {t("time")} :
              </div>
              <Timer isTaskRunning={isTaskRunning} />
            </div>

            <div className="flex flex-row items-baseline gap-2">
              <div
                className={cn(
                  "flex flex-row items-center gap-1 text-xs text-green-500"
                )}
              >
                <DollarSign className="mt-0.5 h-3 w-3" /> {t("usage")} :
              </div>
              <div className="flex flex-row items-baseline gap-2">
                <p className="text-xl">0$</p>
                <p className="text-xs text-muted-foreground/50">
                  {" "}
                  / {t("from")}
                </p>
                <p className="text-sm text-muted-foreground/50">20$</p>
              </div>
            </div>

            <div className="flex flex-row items-baseline gap-2">
              <div
                className={cn(
                  "flex flex-row items-center gap-1 text-xs text-violet-500"
                )}
              >
                <TrendingUp className="mt-0.5 h-3 w-3" /> {t("kpi")} :
              </div>
              <p className="text-xl">-</p>
            </div>
          </div>
        </>
      )}
    </Card>
  );
}
