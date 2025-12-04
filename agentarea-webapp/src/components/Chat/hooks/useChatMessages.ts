/**
 * Hook for managing chat messages state
 * Handles initialization, user message tracking, and message array management
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { MessageComponentType } from "../MessageComponents";

export interface UserChatMessage {
  id: string;
  content: string;
  role: "user";
  timestamp: string;
  files?: File[];
}

export interface WelcomeMessage {
  id: string;
  content: string;
  role: "assistant";
  timestamp: string;
  agent_id: string;
}

export type ChatMessage = UserChatMessage | WelcomeMessage | MessageComponentType;

export interface UseChatMessagesOptions {
  /**
   * Agent name for welcome message
   */
  agentName: string;

  /**
   * Agent ID for welcome message
   */
  agentId: string;

  /**
   * Initial messages to load (optional)
   */
  initialMessages?: ChatMessage[];
}

export interface UseChatMessagesReturn {
  /**
   * Current messages array
   */
  messages: ChatMessage[];

  /**
   * Set messages (full replacement)
   */
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;

  /**
   * Whether the chat has any user messages (not just welcome)
   */
  hasUserMessages: boolean;

  /**
   * Add a user message to the chat
   */
  addUserMessage: (message: UserChatMessage) => void;
}

/**
 * Custom hook for managing chat messages
 *
 * Features:
 * - One-time message initialization (welcome or initialMessages)
 * - Track whether user has sent any messages
 * - Helper to add user messages
 * - Full control over messages array
 *
 * @example
 * ```typescript
 * const {
 *   messages,
 *   setMessages,
 *   hasUserMessages,
 *   addUserMessage
 * } = useChatMessages({
 *   agentName: 'Assistant',
 *   agentId: 'agent-123',
 *   initialMessages: []
 * });
 *
 * // Add user message
 * addUserMessage({
 *   id: '1',
 *   content: 'Hello',
 *   role: 'user',
 *   timestamp: new Date().toISOString()
 * });
 * ```
 */
export function useChatMessages({
  agentName,
  agentId,
  initialMessages = [],
}: UseChatMessagesOptions): UseChatMessagesReturn {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [hasUserMessages, setHasUserMessages] = useState(false);
  const initializedRef = useRef(false);

  /**
   * Check if there are any user messages in the array
   */
  const checkForUserMessages = useCallback((messagesList: ChatMessage[]) => {
    return messagesList.some(
      (message) => "role" in message && message.role === "user"
    );
  }, []);

  /**
   * Initialize messages only once
   */
  useEffect(() => {
    if (!initializedRef.current) {
      initializedRef.current = true;

      if (initialMessages.length > 0) {
        setMessages(initialMessages);
        setHasUserMessages(checkForUserMessages(initialMessages));
      } else {
        // Create default welcome message
        const welcomeMessages: ChatMessage[] = [
          {
            id: "welcome",
            content: `Hello! I'm ${agentName}. How can I help you today?`,
            role: "assistant" as const,
            timestamp: new Date().toISOString(),
            agent_id: agentId,
          } as WelcomeMessage,
        ];
        setMessages(welcomeMessages);
        setHasUserMessages(checkForUserMessages(welcomeMessages));
      }
    }
  }, [agentName, agentId, initialMessages, checkForUserMessages]);

  /**
   * Add a user message to the chat
   * Automatically updates hasUserMessages flag
   */
  const addUserMessage = useCallback(
    (message: UserChatMessage) => {
      setMessages((prev) => {
        const newMessages = [...prev, message];
        setHasUserMessages(checkForUserMessages(newMessages));
        return newMessages;
      });
    },
    [checkForUserMessages]
  );

  return {
    messages,
    setMessages,
    hasUserMessages,
    addUserMessage,
  };
}
