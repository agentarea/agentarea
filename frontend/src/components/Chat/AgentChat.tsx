"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Bot, Send, User, MessageCircle, Paperclip, X, ChevronDown } from "lucide-react";
import { AttachmentCard } from "@/components/ui/attachment-card";
import { useSSE } from "@/hooks/useSSE";
import { MessageRenderer, MessageComponentType } from "./MessageComponents";
import { parseEventToMessage, shouldDisplayEvent } from "./EventParser";
import { UserMessage as UserMessageComponent } from "./componets/UserMessage";
import { AssistantMessage as AssistantMessageComponent } from "./componets/AssistantMessage";
import { cn } from "@/lib/utils";
import { env } from "@/env";

interface UserChatMessage {
  id: string;
  content: string;
  role: "user";
  timestamp: string;
  files?: File[];
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
    description?: string | null;
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
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const currentAssistantMessageRef = useRef<MessageComponentType | null>(null);
  const onTaskCreatedRef = useRef(onTaskCreated);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const initializedRef = useRef(false);
  const scrollTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const scrollRAFRef = useRef<number | null>(null);

  useEffect(() => {
    onTaskCreatedRef.current = onTaskCreated;
  }, [onTaskCreated]);

  // Cleanup timeouts and RAF on unmount
  useEffect(() => {
    return () => {
      if (scrollTimeoutRef.current) {
        clearTimeout(scrollTimeoutRef.current);
      }
      if (scrollRAFRef.current) {
        cancelAnimationFrame(scrollRAFRef.current);
      }
    };
  }, []);

  // SSE connection URL - only connect if we have a task
  const sseUrl = currentTaskId 
    ? `/api/sse/agents/${agent.id}/tasks/${currentTaskId}/events/stream`
    : null;

  // Check if user is at bottom of scroll
  const checkIfAtBottom = useCallback(() => {
    if (!messagesContainerRef.current) return false;
    
    const container = messagesContainerRef.current;
    const threshold = 100; // Увеличиваем порог для более стабильной работы
    const scrollTop = container.scrollTop;
    const clientHeight = container.clientHeight;
    const scrollHeight = container.scrollHeight;
    const isAtBottom = scrollTop + clientHeight >= scrollHeight - threshold;
    
    return isAtBottom;
  }, []);

  // Handle scroll events with debounce
  const handleScroll = useCallback(() => {
    // Отменяем предыдущий таймаут если он есть
    if (scrollTimeoutRef.current) {
      clearTimeout(scrollTimeoutRef.current);
    }
    
    // Устанавливаем новый таймаут для debounce
    scrollTimeoutRef.current = setTimeout(() => {
      const atBottom = checkIfAtBottom();
      setIsAtBottom(atBottom);
    }, 100); // Увеличиваем задержку для более стабильной работы
  }, [checkIfAtBottom]);

  // Auto-scroll to bottom when messages change (only if user was at bottom)
  useEffect(() => {
    if (isAtBottom) {
      // Отменяем предыдущий RAF если он есть
      if (scrollRAFRef.current) {
        cancelAnimationFrame(scrollRAFRef.current);
      }
      
      // Используем requestAnimationFrame для более плавного скролла
      scrollRAFRef.current = requestAnimationFrame(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
        
        // Проверяем позицию после скролла
        scrollRAFRef.current = requestAnimationFrame(() => {
          const atBottom = checkIfAtBottom();
          if (!atBottom) {
            // Принудительно скроллим еще раз если не достигли низа
            messagesEndRef.current?.scrollIntoView({ behavior: "auto" });
          }
        });
      });
    }
  }, [messages, isAtBottom, checkIfAtBottom]);

  // Check scroll position when container size changes
  useEffect(() => {
    const container = messagesContainerRef.current;
    if (container) {
      // Используем RAF для проверки позиции после изменения размера
      const checkPosition = () => {
        const atBottom = checkIfAtBottom();
        setIsAtBottom(atBottom);
      };
      
      scrollRAFRef.current = requestAnimationFrame(checkPosition);
      return () => {
        if (scrollRAFRef.current) {
          cancelAnimationFrame(scrollRAFRef.current);
        }
      };
    }
  }, [messages.length, checkIfAtBottom]);

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
    // Get the actual event type from the data if available
    const actualEventType = event.data?.event_type || event.data?.original_event_type || event.type;
    
    // Handle generic "message" events that might be heartbeats or connection events
    if (actualEventType === 'message' && !event.data?.event_type) {
      // This is likely a heartbeat or connection event - just return
      return;
    }
    
    // Remove workflow prefix if present
    const cleanEventType = actualEventType.replace('workflow.', '');
    
    // Check if this event should create a visible message
    if (!shouldDisplayEvent(cleanEventType)) {
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

    // Special handling for tool call events - replace tool_call_started with tool_result
    if (cleanEventType === 'ToolCallStarted') {
      const originalData = event.data.original_data || event.data;
      const toolName = originalData.tool_name || event.data.tool_name;
      const toolCallId = originalData.tool_call_id || event.data.tool_call_id;

      setMessages(prev => {
        // Check if this tool call has already been started
        const alreadyStarted = prev.some(msg => 
          'type' in msg && 
          msg.type === 'tool_call_started' && 
          (msg.data as any).tool_name === toolName &&
          (msg.data as any).tool_call_id === toolCallId
        );

        if (alreadyStarted) {
          return prev;
        }

        // Create new tool call started message
        const messageComponent = parseEventToMessage(cleanEventType, event.data);
        if (messageComponent) {
          return [...prev, messageComponent];
        }
        return prev;
      });

      return;
    }

    if (cleanEventType === 'ToolCallCompleted') {
      const originalData = event.data.original_data || event.data;
      const toolName = originalData.tool_name || event.data.tool_name;
      const toolCallId = originalData.tool_call_id || event.data.tool_call_id;

      setMessages(prev => {
        // Check if this tool call has already been completed
        const alreadyCompleted = prev.some(msg => 
          'type' in msg && 
          msg.type === 'tool_result' && 
          (msg.data as any).tool_name === toolName &&
          (msg.data as any).tool_call_id === toolCallId
        );

        if (alreadyCompleted) {
          return prev;
        }

        // Find the last tool_call_started message for the same tool and call ID
        const lastToolCallIndex = prev.findLastIndex(msg => 
          'type' in msg && 
          msg.type === 'tool_call_started' && 
          msg.data.tool_name === toolName &&
          msg.data.tool_call_id === toolCallId
        );

        if (lastToolCallIndex !== -1) {
          // Replace the tool_call_started message with tool_result
          const messageComponent = parseEventToMessage(cleanEventType, event.data);
          if (messageComponent) {
            const newMessages = [...prev];
            newMessages[lastToolCallIndex] = messageComponent;
            return newMessages;
          }
        } else {
          // If no matching tool_call_started found, just add the result
          const messageComponent = parseEventToMessage(cleanEventType, event.data);
          if (messageComponent) {
            return [...prev, messageComponent];
          }
        }
        return prev;
      });

      return;
    }

    // Clear any loading state FIRST - before message parsing
    if (cleanEventType === 'WorkflowCompleted' || cleanEventType === 'WorkflowFailed' || cleanEventType === 'task_failed') {
      setIsLoading(false);
    }

    // Parse event into message component for all other event types
    const messageComponent = parseEventToMessage(cleanEventType, event.data);
    if (!messageComponent) {
      return;
    }

    // Add the new message component to the messages
    setMessages(prev => [...prev, messageComponent]);

    // Handle special system events that don't create messages but affect UI state
    switch (cleanEventType) {
      case 'connected':
        break;

      case 'task_created':
        if (event.data.task_id && !currentTaskId) {
          setCurrentTaskId(event.data.task_id);
          onTaskCreatedRef.current?.(event.data.task_id);
        }
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
    // SSE connection opened
  }, []);

  const handleSSEClose = useCallback(() => {
    // SSE connection closed
  }, []);

  // File handling functions
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    setSelectedFiles(prev => [...prev, ...files]);
  };

  const removeFile = (index: number) => {
    setSelectedFiles(prev => prev.filter((_, i) => i !== index));
  };

  const openFileDialog = () => {
    fileInputRef.current?.click();
  };

  // Auto-resize textarea function
  const adjustTextareaHeight = () => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto';
      const scrollHeight = textarea.scrollHeight;
      const maxHeight = 3 * 24; // 3 lines * 24px line height
      textarea.style.height = `${Math.min(scrollHeight, maxHeight)}px`;
    }
  };

  // Handle input change with auto-resize
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    adjustTextareaHeight();
  };

  // Initialize SSE connection
  useSSE(sseUrl, {
    onMessage: handleSSEMessage,
    onError: handleSSEError,
    onOpen: handleSSEOpen,
    onClose: handleSSEClose
  });

  const sendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if ((!input.trim() && selectedFiles.length === 0) || isLoading) return;

    const userMessage: UserChatMessage = {
      id: Date.now().toString(),
      content: input,
      role: "user",
      timestamp: new Date().toISOString(),
      files: selectedFiles.length > 0 ? selectedFiles : undefined,
    };

    // Add user message immediately
    setMessages(prev => [...prev, userMessage]);
    setInput("");
    setSelectedFiles([]);
    setIsLoading(true);
    
    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }

    try {
      // Create task with SSE streaming through Next.js API route (handles auth)
      const response = await fetch(`/api/agents/${agent.id}/tasks/create`, {
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
          user_id: "default_user",
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
    <Card className={cn("flex justify-between flex-col h-full overflow-hidden max-h-full shadow-none p-0 hover:shadow-none cursor-auto", className)}>
      <CardHeader className="border-b p-4">
        <CardTitle className="flex items-center gap-2 ">
          Chat with {agent.name}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex-1 flex flex-col overflow-auto p-0 bg-chatBackground relative">
        {/* Messages */}
        <div 
          ref={messagesContainerRef}
          onScroll={handleScroll}
          className="flex-1 overflow-y-auto space-y-3 py-3 px-3"
        >
          {messages.map((message, index) => {
            // Handle different message types
            if ('type' in message) {
              // This is a MessageComponentType - use MessageRenderer
              return <MessageRenderer key={`${message.data.id}-${message.data.event_type}-${index}`} message={message} agent_name={agent.name} />;
            } else if (message.role === 'user') {
              // User message
              return (
                <UserMessageComponent
                  key={message.id}
                  id={message.id}
                  content={message.content}
                  timestamp={message.timestamp}
                  files={message.files}
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
                  agent_name={agent.name}
                />
              );
            }
          })}
          <div ref={messagesEndRef} className="aa-messages-end" />
        </div>
        
        {/* Scroll to bottom button */}
        <div className={`absolute bottom-4 right-4 z-20 transition-opacity duration-200 ${isAtBottom ? 'opacity-0 pointer-events-none' : 'opacity-100'}`}>
          <Button
            onClick={() => {
              // Принудительно скроллим к низу
              messagesEndRef.current?.scrollIntoView({ behavior: "auto" });
              
              // Проверяем позицию после скролла
              requestAnimationFrame(() => {
                const atBottom = checkIfAtBottom();
                setIsAtBottom(atBottom);
              });
            }}
            size="sm"
            className="h-8 w-8 rounded-full hover:text-white shadow-lg bg-white text-text dark:bg-zinc-900 dark:text-zinc-200 "
          >
            <ChevronDown className="h-4 w-4" />
          </Button>
        </div>
      </CardContent>
      <CardFooter className="p-0">
        {/* Input */}
        <div className="border-t w-full p-4">
          {/* Selected Files Display */}
          {selectedFiles.length > 0 && (
            <div className="mb-3 flex flex-row flex-wrap gap-2">
              {selectedFiles.map((file, index) => (
                <AttachmentCard
                  key={index}
                  file={file}
                  onAction={() => removeFile(index)}
                  actionType="remove"
                />
              ))}
            </div>
          )}
          
          <form onSubmit={sendMessage} className="flex gap-3">
            <div className="flex-1 relative">
              <Textarea
                ref={textareaRef}
                value={input}
                onChange={handleInputChange}
                placeholder={`Message ${agent.name}...`}
                disabled={isLoading}
                className="min-h-[40px] max-h-[72px] resize-none rounded-3xl border focus:border-primary/50 transition-colors duration-200 pr-12 py-2"
                rows={1}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage(e);
                  }
                }}
              />
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={openFileDialog}
                disabled={isLoading}
                className="absolute right-2 top-1 h-8 w-8 p-0 rounded-full hover:text-text hover:bg-zinc-200 dark:hover:bg-gray-800"
              >
                <Paperclip className="h-4 w-4" />
              </Button>
            </div>
            <Button 
              type="submit" 
              size="icon" 
              disabled={isLoading || (!input.trim() && selectedFiles.length === 0)}
              className="rounded-full h-10 w-10 shadow-sm hover:shadow-md transition-all duration-200"
            >
              {isLoading ? (
                <div className="h-4 w-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
            </Button>
          </form>
          
          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            type="file"
            multiple
            onChange={handleFileSelect}
            className="hidden"
            accept="*/*"
          />
        </div>
      </CardFooter>
    </Card>
  );
}