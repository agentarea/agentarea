import React from 'react';
import BaseMessage from './BaseMessage';
import MessageWrapper from './MessageWrapper';

interface ToolCallStartedData {
  tool_name: string;
  tool_call_id: string;
  arguments: Record<string, any>;
}

const ToolCallStartedMessage: React.FC<{ data: ToolCallStartedData }> = ({ data }) => {
  return (
    <MessageWrapper>
      <BaseMessage headerLeft={`Calling ${data.tool_name}...`} >
        {Object.keys(data.arguments).length > 0 && (
          <div className="text-xs text-blue-600 dark:text-blue-400 mt-2">
            <details className="cursor-pointer">
              <summary className="hover:text-blue-700 dark:hover:text-blue-300">Arguments</summary>
              <pre className="mt-1 p-2 bg-blue-100 dark:bg-blue-900/50 rounded text-blue-800 dark:text-blue-200 overflow-x-auto">
                {JSON.stringify(data.arguments, null, 2)}
              </pre>
            </details>
          </div>
        )}
      </BaseMessage>
    </MessageWrapper>
  );
};

export default ToolCallStartedMessage;
