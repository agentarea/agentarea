"use client";

import { Agent } from "@/types/agent";
import Timer from "./Timer";
import ModelBadge from "./ModelBadge";
import ToolsDisplay from "./ToolsDisplay";
import StatCard from "./StatCard";
import { useTranslations } from "next-intl";

interface Props {
    agent: Agent;
    isTaskRunning?: boolean;
}

export default function AgentDetails({ agent, isTaskRunning = false }: Props) {
    const t = useTranslations("Agent.descriptionPage");
    return (
        <div className="w-full flex flex-row gap-2">
            {/* <div className="w-full card">
                <Timer isTaskRunning={isTaskRunning} />
                <div className="flex flex-row gap-2">
                    <h3>Money:</h3>
                    <p>00 $</p>
                </div>
                <div className="flex flex-row gap-2">
                    <h3>KPI:</h3>
                    <p>100%</p>
                </div>
            </div> */}
            <div className="w-full card flex flex-row gap-6 col-span-5 flex-1 py-2 px-4">
                <div className="flex flex-col space-y-2 flex-1">
                    <div className="flex flex-row gap-2 items-center">
                        <p className="text-xs">{t("model")}:</p >
                            <ModelBadge modelId={agent.model_id} />
                    </div>
                    <div className="flex flex-row gap-2 items-center">
                        <p className="text-xs">{t("tools")}:</p >
                        <ToolsDisplay agent={agent} />
                    </div>
                </div>
                
                <div className="flex flex-row gap-2 items-top flex-1">
                    <p className="text-xs mt-0.5">{t("description")}:</p>
                    <p className="text-sm text-gray-500 line-clamp-4 overflow-hidden">
                        {agent.description || "No description available"}
                    </p>
                </div>
            </div>

            <div className="w-full grid grid-cols-3 gap-1 flex-1">
                <StatCard type="timer">
                    <Timer isTaskRunning={isTaskRunning} />
                </StatCard>
                <StatCard type="money">
                    <div className="flex flex-row gap-2 items-baseline">
                        <p className="text-4xl">0$</p>
                        <p className="text-xs text-muted-foreground">{t("from")}</p>
                        <p className="text-sm text-muted-foreground">20$</p>
                    </div>
                </StatCard>
                <StatCard type="kpi">
                    <div className="flex flex-row gap-2 items-baseline">
                        <p className="text-4xl">0</p>
                        <p className="text-xs text-muted-foreground">/</p>
                        <p className="text-sm text-muted-foreground">20 users</p>
                    </div>
                </StatCard>
            </div>
        </div>
    )
}