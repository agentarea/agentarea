import MessageWrapper from './MessageWrapper';
import { LLMResponseData } from '../types';
import BaseMessage from './BaseMessage';
import { formatTimestamp } from '../../../utils/dateUtils';
import { Streamdown } from 'streamdown';

export const LLMResponseMessage: React.FC<{ data: LLMResponseData, agent_name?: string }> = ({ data, agent_name }) => {
    return (
      <MessageWrapper>
        <BaseMessage headerLeft={agent_name || "Assistant"} headerRight={formatTimestamp(data.timestamp)}>
            <Streamdown className="prose prose-sm dark:prose-invert max-w-none" components={{ think: ({ children }: any) => (
              <div className="text-xs text-gray-400 dark:text-gray-300">{children}</div>
            ) } as any}>
              {data.content}
            </Streamdown>
            {data.usage && (
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-3 pt-2 border-t border-gray-200 dark:border-gray-700 flex gap-4">
                    <span>Tokens: {data.usage.usage.total_tokens}</span>
                    <span>Cost: ${data.usage.cost.toFixed(4)}</span>
                </div>
            )}
        </BaseMessage>
      </MessageWrapper>
    );
  };  

export default LLMResponseMessage;