import React from "react";
import { useLocale } from "next-intl";
import { SplitBudgetDisplay } from "@/components/BudgetDisplay";
import { useCurrency } from "@/hooks/useCurrency";
import { formatMoney } from "@/lib/money";
import BaseMessage from "./BaseMessage";
import MessageWrapper from "./MessageWrapper";

interface WorkflowResultData {
  result?: string;
  final_response?: string;
  success: boolean;
  iterations_completed?: number;
  total_cost?: number | string;
  budget_usd?: number;
  service_cost_used?: number;
  service_budget_usd?: number;
}

const WorkflowResultMessage: React.FC<{
  data: WorkflowResultData;
  agent_name?: string;
}> = ({ data, agent_name: _agent_name }) => {
  const locale = useLocale();
  const { currency } = useCurrency();
  const content = data.result || data.final_response || "";
  const hasServiceBudget =
    data.service_budget_usd != null && data.service_budget_usd > 0;

  return (
    <MessageWrapper>
      <BaseMessage headerLeft={"Workflow Result"} headerRight={null}>
        <div className="whitespace-pre-wrap text-sm leading-relaxed">
          {content}
        </div>
        {(data.budget_usd || hasServiceBudget) && (
          <div className="mt-3 border-t border-gray-200 pt-3 dark:border-gray-700">
            <SplitBudgetDisplay
              inferenceBudget={data.budget_usd}
              inferenceCost={Number(data.total_cost) || 0}
              serviceBudget={data.service_budget_usd}
              serviceCost={data.service_cost_used}
            />
          </div>
        )}
        {(data.iterations_completed || data.total_cost) && !data.budget_usd && (
          <div className="mt-3 flex gap-4 border-t border-gray-200 pt-2 text-xs text-gray-500 dark:border-gray-700 dark:text-gray-400">
            {data.iterations_completed && (
              <span>Iterations: {data.iterations_completed}</span>
            )}
            {data.total_cost && (
              <span>
                Total Cost:{" "}
                {formatMoney(Number(data.total_cost), currency, locale)}
              </span>
            )}
          </div>
        )}
      </BaseMessage>
    </MessageWrapper>
  );
};

export default WorkflowResultMessage;
