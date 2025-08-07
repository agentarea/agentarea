"use client";

import React, { useState, useEffect, useRef } from "react";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Bot, Send, User, Loader2 } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { getChatAgents, sendMessage as sendChatMessage, getChatMessageStatus } from "@/lib/api";
import { LoadingSpinner } from '@/components/LoadingSpinner';

// Types
interface Agent {
  id: string;
  name: string;
  description: string;
  status: string;
}

interface Message {
  id: string;
  content: string;
  role: "user" | "assistant";
  timestamp: string;
  agent_id?: string;
}

export default function ChatPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingAgents, setIsLoadingAgents] = useState(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Focus input on load
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Load agents on mount
  useEffect(() => {
    loadAgents();
  }, []);

  // Load welcome message when agent changes
  useEffect(() => {
    if (selectedAgent) {
      setMessages([
        {
          id: "welcome",
          content: `Hello! I'm ${selectedAgent.name}. How can I help you today?`,
          role: "assistant",
          timestamp: new Date().toISOString(),
          agent_id: selectedAgent.id,
        },
      ]);
    }
  }, [selectedAgent]);

  const loadAgents = async () => {
    try {
      setIsLoadingAgents(true);
      const { data: agentData, error } = await getChatAgents();
      if (error) {
        console.error("Failed to load agents:", error);
      } else if (agentData) {
        setAgents(agentData);
        
        // Auto-select first agent if available
        if (agentData.length > 0) {
          setSelectedAgent(agentData[0]);
        }
      }
    } catch (error) {
      console.error("Error loading agents:", error);
    } finally {
      setIsLoadingAgents(false);
    }
  };

  const sendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || !selectedAgent || isLoading) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      content: input,
      role: "user",
      timestamp: new Date().toISOString(),
    };

    // Add user message immediately
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);

    try {
      // Send to chat API - returns immediately with task_id
      const { data: responseData, error } = await sendChatMessage({
        content: userMessage.content,
        agent_id: selectedAgent.id,
        user_id: "frontend_user",
      });

      if (error) {
        const errorMessage: Message = {
          id: (Date.now() + 1).toString(),
          content: `Sorry, I encountered an error: ${error}`,
          role: "assistant",
          timestamp: new Date().toISOString(),
          agent_id: selectedAgent.id,
        };
        setMessages((prev) => [...prev, errorMessage]);
        setIsLoading(false);
      } else if (responseData) {
        // Add placeholder message while agent processes
        const placeholderMessage: Message = {
          id: responseData.task_id || (Date.now() + 1).toString(),
          content: "🤔 Thinking...",
          role: "assistant",
          timestamp: responseData.timestamp || new Date().toISOString(),
          agent_id: selectedAgent.id,
        };

        setMessages((prev) => [...prev, placeholderMessage]);
        
        // Start polling for the real response
        if (responseData.task_id) {
          pollForResponse(responseData.task_id);
        } else {
          // Fallback: update with immediate content if no task_id
          setMessages((prev) => prev.map(msg => 
            msg.id === placeholderMessage.id 
              ? { ...msg, content: responseData.content || "Response received" }
              : msg
          ));
          setIsLoading(false);
        }
      }
    } catch (error) {
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        content: `Sorry, I couldn't process your message. Error: ${error}`,
        role: "assistant",
        timestamp: new Date().toISOString(),
        agent_id: selectedAgent.id,
      };
      setMessages((prev) => [...prev, errorMessage]);
      setIsLoading(false);
    }
  };

  const pollForResponse = async (taskId: string) => {
    const maxPolls = 60; // Poll for up to 5 minutes (60 * 5s = 5min)
    let pollCount = 0;

    const poll = async () => {
      try {
        const { data: status, error } = await getChatMessageStatus(taskId);
        
        if (error) {
          throw new Error("Failed to check message status");
        }
        
        if (status?.status === "completed") {
          // Update placeholder with real response
          setMessages((prev) => prev.map(msg => 
            msg.id === taskId 
              ? { ...msg, content: status.content, timestamp: status.timestamp }
              : msg
          ));
          setIsLoading(false);
        } else if (status?.status === "failed") {
          // Update with error message
          setMessages((prev) => prev.map(msg => 
            msg.id === taskId 
              ? { ...msg, content: `I apologize, but I encountered an error: ${status.error || "Unknown error"}` }
              : msg
          ));
          setIsLoading(false);
        } else if (pollCount < maxPolls) {
          // Still processing, continue polling
          pollCount++;
          setTimeout(poll, 5000); // Poll every 5 seconds
        } else {
          // Timeout after max polls
          setMessages((prev) => prev.map(msg => 
            msg.id === taskId 
              ? { ...msg, content: "Sorry, the request timed out. Please try again." }
              : msg
          ));
          setIsLoading(false);
        }
        
      } catch (error) {
        console.error("Error polling for response:", error);
        setMessages((prev) => prev.map(msg => 
          msg.id === taskId 
            ? { ...msg, content: "Sorry, there was an error getting the response. Please try again." }
            : msg
        ));
        setIsLoading(false);
      }
    };

    // Start polling immediately
    poll();
  };

  return (
    <div className="flex flex-col h-screen bg-background">
      <div className="border-b border-border px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-foreground">
              AgentArea Chat
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              Chat with your real agents
            </p>
          </div>
          
          {/* Agent Selector */}
          <div className="w-64">
            <Select
              value={selectedAgent?.id || ""}
              onValueChange={(agentId) => {
                const agent = agents.find(a => a.id === agentId);
                if (agent) setSelectedAgent(agent);
              }}
              disabled={isLoadingAgents}
            >
              <SelectTrigger>
                <SelectValue placeholder={isLoadingAgents ? "Loading agents..." : "Select an agent"} />
              </SelectTrigger>
              <SelectContent>
                {agents.map((agent) => (
                  <SelectItem key={agent.id} value={agent.id}>
                    <div className="flex flex-col">
                      <span className="font-medium">{agent.name}</span>
                      <span className="text-xs text-muted-foreground truncate">
                        {agent.description}
                      </span>
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>
      
      <div className="flex-1 p-6">
        <Card className="h-full flex flex-col">
          {selectedAgent && (
            <CardHeader className="border-b">
              <div className="flex items-center space-x-4">
                <Avatar className="h-10 w-10 bg-primary/10">
                  <AvatarFallback>
                    <Bot className="h-5 w-5" />
                  </AvatarFallback>
                </Avatar>
                <div>
                  <CardTitle className="text-lg">{selectedAgent.name}</CardTitle>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-xs">
                      {selectedAgent.status}
                    </Badge>
                    <span className="text-sm text-muted-foreground">
                      {selectedAgent.description}
                    </span>
                  </div>
                </div>
              </div>
            </CardHeader>
          )}
          
          <CardContent className="flex-1 overflow-y-auto p-6">
            {!selectedAgent ? (
              <div className="flex items-center justify-center h-full text-muted-foreground">
                {isLoadingAgents ? (
                  <LoadingSpinner />
                ) : agents.length === 0 ? (
                  <div className="text-center">
                    <p>No agents available.</p>
                    <p className="text-sm mt-2">
                      Create an agent first in the{" "}
                      <a href="/agents/create" className="text-primary hover:underline">
                        agent creation page
                      </a>
                      .
                    </p>
                  </div>
                ) : (
                  <p>Select an agent to start chatting</p>
                )}
              </div>
            ) : (
              <div className="space-y-4">
                {messages.map((message) => (
                  <div
                    key={message.id}
                    className={`flex ${
                      message.role === "user" ? "justify-end" : "justify-start"
                    }`}
                  >
                    <div
                      className={`flex max-w-[80%] ${
                        message.role === "user" ? "flex-row-reverse" : "flex-row"
                      }`}
                    >
                      <Avatar className="h-8 w-8 mt-1 mx-2">
                        <AvatarFallback>
                          {message.role === "user" ? (
                            <User className="h-4 w-4" />
                          ) : (
                            <Bot className="h-4 w-4" />
                          )}
                        </AvatarFallback>
                      </Avatar>
                      
                      <div
                        className={`rounded-lg p-4 ${
                          message.role === "user"
                            ? "bg-primary text-primary-foreground"
                            : "bg-muted"
                        }`}
                      >
                        <p className="whitespace-pre-wrap">{message.content}</p>
                        <p className="text-xs opacity-70 mt-2">
                          {new Date(message.timestamp).toLocaleTimeString()}
                        </p>
                      </div>
                    </div>
                  </div>
                ))}
                <div ref={messagesEndRef} />
              </div>
            )}
          </CardContent>
          
          {selectedAgent && (
            <CardFooter className="border-t p-4">
              <form onSubmit={sendMessage} className="flex w-full items-center space-x-2">
                <Input
                  ref={inputRef}
                  type="text"
                  placeholder={`Message ${selectedAgent.name}...`}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  className="flex-1"
                  disabled={isLoading}
                />
                <Button 
                  type="submit" 
                  size="icon" 
                  disabled={isLoading || input.trim() === ""}
                >
                  {isLoading ? (
                    <Loader2 className="h-5 w-5 animate-spin" />
                  ) : (
                    <Send className="h-5 w-5" />
                  )}
                </Button>
              </form>
            </CardFooter>
          )}
        </Card>
      </div>
    </div>
  );
} 