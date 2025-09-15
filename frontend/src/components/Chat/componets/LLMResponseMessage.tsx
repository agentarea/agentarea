import MessageWrapper from './MessageWrapper';
import { LLMResponseData } from '../types';
import BaseMessage from './BaseMessage';
import { formatTimestamp } from '../../../utils/dateUtils';

export const LLMResponseMessage: React.FC<{ data: LLMResponseData }> = ({ data }) => {
    return (
      <MessageWrapper>
        <BaseMessage headerLeft={"Assistant"} headerRight={formatTimestamp(data.timestamp)}>
            {data.content}
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