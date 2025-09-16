"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Bot, Send, User, MessageCircle } from "lucide-react";
import { useSSE } from "@/hooks/useSSE";
import { MessageRenderer, MessageComponentType } from "./MessageComponents";
import { parseEventToMessage, shouldDisplayEvent } from "./EventParser";
import { UserMessage as UserMessageComponent } from "./componets/UserMessage";
import { AssistantMessage as AssistantMessageComponent } from "./componets/AssistantMessage";
import { cn } from "@/lib/utils";

interface UserChatMessage {
  id: string;
  content: string;
  role: "user";
  timestamp: string;
}

interface WelcomeMessage {
  id: string;
  content: string;
  role: "assistant";
  timestamp: string;
  agent_id: string;
}

type ChatMessage = UserChatMessage | WelcomeMessage | MessageComponentType;

interface AgentChatProps {
  agent: {
    id: string;
    name: string;
    description?: string;
  };
  taskId?: string;
  initialMessages?: ChatMessage[];
  onTaskCreated?: (taskId: string) => void;
  className?: string;
  height?: string;
}

export default function AgentChat({
  agent,
  taskId,
  initialMessages = [],
  onTaskCreated,
  className = "",
  height = "600px"
}: AgentChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(taskId || null);
  const currentAssistantMessageRef = useRef<MessageComponentType | null>(null);
  const onTaskCreatedRef = useRef(onTaskCreated);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const initializedRef = useRef(false);

  useEffect(() => {
    onTaskCreatedRef.current = onTaskCreated;
  }, [onTaskCreated]);

  // SSE connection URL - only connect if we have a task
  const sseUrl = currentTaskId 
    ? `/api/sse/agents/${agent.id}/tasks/${currentTaskId}/events/stream`
    : null;

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Initialize messages only once
  useEffect(() => {
    if (!initializedRef.current) {
      initializedRef.current = true;
      if (initialMessages.length > 0) {
        setMessages(initialMessages);
      } else {
        setMessages([
          {
            id: "welcome",
            content: `Hello! I'm ${agent.name}. How can I help you today?`,
            role: "assistant" as const,
            timestamp: new Date().toISOString(),
            agent_id: agent.id,
          } as WelcomeMessage,
        ]);
      }
    }
  }, []); // Empty dependency array - only run once

  // Handle SSE events
  const handleSSEMessage = useCallback((event: { type: string; data: any }) => {
    console.log('SSE Event received (UPDATED VERSION):', event);

    // Get the actual event type from the data if available
    const actualEventType = event.data?.event_type || event.data?.original_event_type || event.type;
    
    // Handle generic "message" events that might be heartbeats or connection events
    if (actualEventType === 'message' && !event.data?.event_type) {
      // This is likely a heartbeat or connection event - just log it
      console.log('Heartbeat/connection event received:', event.data);
      return;
    }
    
    // Remove workflow prefix if present
    const cleanEventType = actualEventType.replace('workflow.', '');
    
    console.log('Processing event type:', cleanEventType, 'Category:', event.data?.event_category);
    console.log('Event data:', event.data);
    
    // Check if this event should create a visible message
    if (!shouldDisplayEvent(cleanEventType)) {
      console.log(`Skipping non-displayable event: ${cleanEventType}`);
      return;
    }

    // Special handling for chunk events - accumulate instead of creating new messages
    if (cleanEventType === 'LLMCallChunk') {
      const originalData = event.data.original_data || event.data;
      const chunk = originalData.chunk || event.data.chunk;
      const chunkIndex = originalData.chunk_index || event.data.chunk_index || 0;
      const isFinal = originalData.is_final || event.data.is_final || false;
      const taskId = originalData.task_id || event.data.task_id;

      setMessages(prev => {
        const lastMessage = prev[prev.length - 1];
        
        // If the last message is a streaming message from the same task, append to it
        if (lastMessage && 
            'type' in lastMessage && 
            lastMessage.type === 'llm_chunk' &&
            lastMessage.data.id === taskId) {
          
          // Update the existing streaming message
          const updatedMessage = {
            ...lastMessage,
            data: {
              ...lastMessage.data,
              chunk: lastMessage.data.chunk + chunk,
              chunk_index: chunkIndex,
              is_final: isFinal
            }
          };
          
          return [...prev.slice(0, -1), updatedMessage];
        } else {
          // Create new streaming message
          const messageComponent = parseEventToMessage(cleanEventType, event.data);
          if (messageComponent) {
            return [...prev, messageComponent];
          }
          return prev;
        }
      });

      // Convert to final message when streaming is complete
      if (isFinal) {
        setMessages(prev => {
          const lastMessage = prev[prev.length - 1];
          if (lastMessage && 
              'type' in lastMessage && 
              lastMessage.type === 'llm_chunk' &&
              lastMessage.data.id === taskId) {
            
            // Convert to final llm_response message
            const finalMessage: MessageComponentType = {
              type: 'llm_response',
              data: {
                id: lastMessage.data.id,
                timestamp: lastMessage.data.timestamp,
                agent_id: lastMessage.data.agent_id,
                event_type: 'LLMCallCompleted',
                content: lastMessage.data.chunk,
                role: 'assistant'
              }
            };
            
            return [...prev.slice(0, -1), finalMessage];
          }
          return prev;
        });
      }

      return;
    }

    // Clear any loading state FIRST - before message parsing
    if (cleanEventType === 'WorkflowCompleted' || cleanEventType === 'WorkflowFailed' || cleanEventType === 'task_failed') {
      console.log(`Clearing loading state for event: ${cleanEventType}`);
      setIsLoading(false);
    }

    // Parse event into message component for all other event types
    const messageComponent = parseEventToMessage(cleanEventType, event.data);
    if (!messageComponent) {
      console.log(`No message component created for event: ${cleanEventType}`);
      return;
    }

    console.log(`Creating message component of type: ${messageComponent.type}`);

    // Add the new message component to the messages
    setMessages(prev => [...prev, messageComponent]);

    // Handle special system events that don't create messages but affect UI state
    switch (cleanEventType) {
      case 'connected':
        console.log('Connected to task stream');
        break;

      case 'task_created':
        if (event.data.task_id && !currentTaskId) {
          setCurrentTaskId(event.data.task_id);
          onTaskCreatedRef.current?.(event.data.task_id);
        }
        console.log('Task created, waiting for workflow events...');
        break;

      case 'error':
        console.error('SSE error:', event.data);
        setIsLoading(false);
        break;
        
      default:
        // All other events are handled by the message parsing above
        break;
    }
  }, [agent.id]); // Remove dependencies that cause frequent recreation

  // SSE event handlers
  const handleSSEError = useCallback((error: Event) => {
    console.error('SSE connection error:', error);
    setIsLoading(false);
  }, []);

  const handleSSEOpen = useCallback(() => {
    console.log('SSE connection opened');
  }, []);

  const handleSSEClose = useCallback(() => {
    console.log('SSE connection closed');
  }, []);

  // Initialize SSE connection
  useSSE(sseUrl, {
    onMessage: handleSSEMessage,
    onError: handleSSEError,
    onOpen: handleSSEOpen,
    onClose: handleSSEClose
  });

  const sendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMessage: UserChatMessage = {
      id: Date.now().toString(),
      content: input,
      role: "user",
      timestamp: new Date().toISOString(),
    };

    // Add user message immediately
    setMessages(prev => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);

    try {
      // Create task with SSE streaming
      const baseUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const response = await fetch(`${baseUrl}/v1/agents/${agent.id}/tasks/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
        },
        body: JSON.stringify({
          description: userMessage.content,
          parameters: {
            context: {},
            task_type: "chat",
            session_id: `chat-${Date.now()}`,
          },
          user_id: "frontend_user",
          enable_agent_communication: true,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      if (!response.body) {
        throw new Error('No response body');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const chunk = decoder.decode(value);
          const lines = chunk.split('\n');

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const eventData = JSON.parse(line.slice(6));
                handleSSEMessage({ type: eventData.type || 'message', data: eventData.data || eventData });
              } catch (parseError) {
                console.error('Failed to parse SSE event:', parseError);
              }
            }
          }
        }
      } finally {
        reader.releaseLock();
      }

    } catch (error) {
      console.error('Failed to send message:', error);
      const errorMessage: WelcomeMessage = {
        id: (Date.now() + 1).toString(),
        content: `Sorry, I couldn't process your message. Error: ${error}`,
        role: "assistant",
        timestamp: new Date().toISOString(),
        agent_id: agent.id,
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Card className={cn("flex justify-between flex-col h-full max-h-full shadow-none p-0 hover:shadow-none cursor-auto", className)}>
      <CardHeader className="border-b p-4">
        <CardTitle className="flex items-center gap-2 ">
          Chat with {agent.name}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex-1 flex flex-col overflow-auto p-0 bg-chatBackground">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto space-y-3 py-3 px-3">
          {messages.map((message, index) => {
            // Handle different message types
            if ('type' in message) {
              // This is a MessageComponentType - use MessageRenderer
              return <MessageRenderer key={`${message.data.id}-${message.data.event_type}-${index}`} message={message} />;
            } else if (message.role === 'user') {
              // User message
              return (
                <UserMessageComponent
                  key={message.id}
                  id={message.id}
                  content={message.content}
                  timestamp={message.timestamp}
                />
              );
            } else {
              // Assistant welcome message
              return (
                <AssistantMessageComponent
                  key={message.id}
                  id={message.id}
                  content={message.content}
                  timestamp={message.timestamp}
                  agent_id={message.agent_id}
                />
              );
            }
          })}
          <div ref={messagesEndRef} className="aa-messages-end" />
        </div>
      </CardContent>
      <CardFooter className="p-0">
        {/* Input */}
        <div className="border-t w-full p-4">
          <form onSubmit={sendMessage} className="flex gap-3">
            <Input
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={`Message ${agent.name}...`}
              disabled={isLoading}
              className="flex-1 rounded-full border-2 focus:border-primary/50 transition-colors duration-200"
            />
            <Button 
              type="submit" 
              size="icon" 
              disabled={isLoading || !input.trim()}
              className="rounded-full h-10 w-10 shadow-sm hover:shadow-md transition-all duration-200"
            >
              {isLoading ? (
                <div className="h-4 w-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
            </Button>
          </form>
        </div>
      </CardFooter>
    </Card>
  );
}