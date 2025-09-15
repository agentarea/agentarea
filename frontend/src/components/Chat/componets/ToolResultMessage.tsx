import React from 'react';
import BaseMessage from './BaseMessage';
import MessageWrapper from './MessageWrapper';

interface ToolResultData {
  tool_name: string;
  result: any;
  success: boolean;
  execution_time?: string;
  arguments?: Record<string, any>;
}

const ToolResultMessage: React.FC<{ data: ToolResultData }> = ({ data }) => {
  const formatResult = (result: any) => {
    if (typeof result === 'string') {
      return result;
    }
    return JSON.stringify(result, null, 2);
  };

  const getStatusColor = () => {
    if (data.success === false) {
      return {
        container: "bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-800",
        header: "text-red-700 dark:text-red-300",
        content: "text-red-800 dark:text-red-200",
        icon: "\u274c"
      };
    }
    return {
      container: "bg-green-50 dark:bg-green-950/30 border-green-200 dark:border-green-800",
      header: "text-green-700 dark:text-green-300",
      content: "text-green-800 dark:text-green-200",
      icon: "\u2705"
    };
  };

  const colors = getStatusColor();

  return (
    <MessageWrapper>
      <BaseMessage headerLeft={<span>{`Tool Result: ${data.tool_name}`}</span>}>
        <div className={`text-sm leading-relaxed ${colors.content}`}>
          <pre className="whitespace-pre-wrap overflow-x-auto">
            {formatResult(data.result)}
          </pre>
        </div>
        {Object.keys(data.arguments || {}).length > 0 && (
          <div className="mt-3 pt-2 border-t border-current/20">
            <details className="cursor-pointer">
              <summary className={`text-xs ${colors.header} hover:opacity-80`}>Arguments</summary>
              <pre className="mt-1 p-2 bg-black/5 dark:bg-white/5 rounded text-xs overflow-x-auto">
                {JSON.stringify(data.arguments, null, 2)}
              </pre>
            </details>
          </div>
        )}
        {data.execution_time && (
          <div className={`text-xs mt-2 pt-2 border-t border-current/20 ${colors.header}`}>
            Execution time: {data.execution_time}
          </div>
        )}
      </BaseMessage>
    </MessageWrapper>
  );
};

export default ToolResultMessage;
