import { Card } from "@/components/ui/card";
import ModelBadge from "@/components/ui/ModelBadge";
import ToolsDisplay from "./ToolsDisplay";
import { useTranslations } from "next-intl";
import { Agent } from "@/types/agent";
import { cn } from "@/lib/utils";
import { Clock, DollarSign, TrendingUp } from "lucide-react";
import Timer from "./Timer";

interface Props {
    agent: Agent;
    isTaskRunning?: boolean;
    isTaskActive?: boolean;
}

export default function TaskDetails({ agent, isTaskRunning = false, isTaskActive = false }: Props) {
    const t = useTranslations("Agent.descriptionPage");
    return (
        <Card className="
            h-full flex flex-col overflow-auto gap-3
            md:min-w-[250px] lg:min-w-[300px] md:max-w-[250px] lg:max-w-[300px]
        ">
            <h3 className="">{t("agentDetails")}</h3>
            <div className="flex flex-col space-y-2">
                <div className="flex flex-row gap-2 items-center">
                    <p className="text-xs">{t("model")}:</p >
                        <ModelBadge modelId={agent.model_id} />
                </div>
                <div className="flex flex-row gap-2 items-center">
                    <p className="text-xs">{t("tools")}:</p >
                    <ToolsDisplay agent={agent} />
                </div>
                {agent.description &&<div className="flex flex-row gap-2 items-start flex-1">
                    <p className="text-xs mt-0.5">{t("description")}:</p>
                    <p className="text-xs text-gray-500 line-clamp-2 overflow-hidden flex-1 min-w-0">
                        {agent.description}
                    </p>
                </div>}
            </div>

            {isTaskActive && (
                <>
                    <h3 className="mt-5">{t("taskDetails")}</h3>
                    <div className="flex flex-col space-y-2">
                        <div className="flex flex-row gap-2 items-baseline">
                            <div className={cn("text-xs text-primary flex flex-row gap-1 items-center")}>
                                <Clock className="h-3 w-3 mt-0.5"/> {t("time")} :
                            </div>
                            <Timer isTaskRunning={isTaskRunning} />
                        </div>

                        <div className="flex flex-row gap-2 items-baseline">
                            <div className={cn("text-xs text-green-500 flex flex-row gap-1 items-center")}>
                            <DollarSign className="h-3 w-3 mt-0.5"/> {t("usage")} :
                            </div>
                            <div className="flex flex-row gap-2 items-baseline">
                                <p className="text-xl">0$</p>
                                <p className="text-xs text-muted-foreground/50"> / {t("from")}</p>
                                <p className="text-sm text-muted-foreground/50">20$</p>
                            </div>
                        </div>

                        <div className="flex flex-row gap-2 items-baseline">
                            <div className={cn("text-xs text-violet-500 flex flex-row gap-1 items-center")}>
                            <TrendingUp className="h-3 w-3 mt-0.5"/> {t("kpi")} :
                            </div>
                            <p className="text-xl">-</p>
                        </div>
                    </div>
                </>
            )}
        </Card>
    );
}