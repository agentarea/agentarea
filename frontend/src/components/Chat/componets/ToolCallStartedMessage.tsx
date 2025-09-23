import React, { useState, useEffect } from 'react';
import { Settings } from 'lucide-react';
import BaseMessage from './BaseMessage';
import MessageWrapper from './MessageWrapper';
import { useTranslations } from 'next-intl';

interface ToolCallStartedData {
  tool_name: string;
  tool_call_id: string;
  arguments: Record<string, any>;
}

const ToolCallStartedMessage: React.FC<{ data: ToolCallStartedData }> = ({ data }) => {
  const [showCalling, setShowCalling] = useState(true);
  const t = useTranslations("Chat.Messages");

  useEffect(() => {
    // Показываем "calling..." постоянно, пока не заменится на результат
  }, [data]);

  return (
    <MessageWrapper type="tool-call" >
      <BaseMessage 
        headerLeft={`${t("toolCall")}: ${data.tool_name}`} 
        headerRight={
          <div className="flex items-center gap-2">
            {showCalling && (
              <Settings 
                className="w-4 h-4 text-blue-500" 
                style={{ 
                  animation: 'spin 2.5s linear infinite',
                  transformOrigin: 'center'
                }}
              />
            )}
            <span className={showCalling ? "animate-pulse text-blue-600" : ""}>
              {showCalling ? `${t("calling")}...` : `${t("processing")}...`}
            </span>
          </div>
        } 
        collapsed={true}
      >
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
