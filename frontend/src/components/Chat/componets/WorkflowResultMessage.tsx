import React from 'react';
import BaseMessage from './BaseMessage';
import MessageWrapper from './MessageWrapper';

interface WorkflowResultData {
  result?: string;
  final_response?: string;
  success: boolean;
  iterations_completed?: number;
  total_cost?: number;
}

const WorkflowResultMessage: React.FC<{ data: WorkflowResultData, agent_name?: string }> = ({ data, agent_name }) => {
  const content = data.result || data.final_response || '';
  
  return (
    <MessageWrapper>
        <BaseMessage headerLeft={"Workflow Result"} headerRight={null}>
            <div className="text-sm leading-relaxed whitespace-pre-wrap">
                {content}
            </div>
            {(data.iterations_completed || data.total_cost) && (
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-3 pt-2 border-t border-gray-200 dark:border-gray-700 flex gap-4">
                {data.iterations_completed && <span>Iterations: {data.iterations_completed}</span>}
                {data.total_cost && <span>Total Cost: ${data.total_cost.toFixed(4)}</span>}
                </div>
            )}
        </BaseMessage>
    </MessageWrapper>
  );
};

export default WorkflowResultMessage;
