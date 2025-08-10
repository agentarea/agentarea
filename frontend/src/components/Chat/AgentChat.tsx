"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Bot, Send, User, MessageCircle } from "lucide-react";
import { useSSE } from "@/hooks/useSSE";
import { MessageRenderer, MessageComponentType } from "./MessageComponents";
import { parseEventToMessage, shouldDisplayEvent } from "./EventParser";


interface UserMessage {
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

type ChatMessage = UserMessage | WelcomeMessage | MessageComponentType;

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

    // Parse event into message component
    const messageComponent = parseEventToMessage(cleanEventType, event.data);
    if (!messageComponent) {
      console.log(`No message component created for event: ${cleanEventType}`);
      return;
    }

    console.log(`Creating message component of type: ${messageComponent.type}`);

    // Add the new message component to the messages
    setMessages(prev => [...prev, messageComponent]);
    
    // Clear any loading state
    if (cleanEventType === 'WorkflowCompleted' || cleanEventType === 'WorkflowFailed' || cleanEventType === 'task_failed') {
      setIsLoading(false);
    }

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

    const userMessage: UserMessage = {
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
    <Card className={`flex flex-col shadow-sm border-0 bg-gradient-to-b from-background to-muted/20 ${className}`} style={{ height }}>
      <CardHeader className="border-b bg-background/50 backdrop-blur-sm">
        <CardTitle className="flex items-center gap-2">
          <MessageCircle className="h-5 w-5 text-primary" />
          Chat with {agent.name}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex-1 flex flex-col p-0">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto space-y-4 p-4">
          {messages.map((message) => {
            // Handle different message types
            if ('type' in message) {
              // This is a MessageComponentType - use MessageRenderer
              return <MessageRenderer key={message.data.id} message={message} />;
            } else if (message.role === 'user') {
              // User message
              return (
                <div key={message.id} className="flex gap-3 animate-in slide-in-from-bottom-2 duration-300 justify-end">
                  <div className="max-w-[80%] rounded-2xl px-4 py-3 shadow-sm transition-all duration-200 hover:shadow-md bg-primary text-primary-foreground">
                    <p className="text-sm leading-relaxed whitespace-pre-wrap">{message.content}</p>
                    <p className="text-xs opacity-70 mt-2">
                      {new Date(message.timestamp).toLocaleTimeString()}
                    </p>
                  </div>
                  <Avatar className="h-8 w-8 border-2 border-muted">
                    <AvatarFallback className="bg-muted">
                      <User className="h-4 w-4" />
                    </AvatarFallback>
                  </Avatar>
                </div>
              );
            } else {
              // Assistant welcome message
              return (
                <div key={message.id} className="flex gap-3 animate-in slide-in-from-bottom-2 duration-300 justify-start">
                  <Avatar className="h-8 w-8 border-2 border-primary/20">
                    <AvatarFallback className="bg-primary/10">
                      <Bot className="h-4 w-4 text-primary" />
                    </AvatarFallback>
                  </Avatar>
                  <div className="max-w-[80%] rounded-2xl px-4 py-3 shadow-sm transition-all duration-200 hover:shadow-md bg-background border border-border">
                    <p className="text-sm leading-relaxed whitespace-pre-wrap">{message.content}</p>
                    <p className="text-xs opacity-70 mt-2">
                      {new Date(message.timestamp).toLocaleTimeString()}
                    </p>
                  </div>
                </div>
              );
            }
          })}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="border-t bg-background/80 backdrop-blur-sm p-4">
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
      </CardContent>
    </Card>
  );
}