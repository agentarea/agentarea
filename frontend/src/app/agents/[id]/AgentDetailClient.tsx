"use client";

import React, { useState, useEffect, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { 
  Bot, 
  Edit, 
  Send, 
  MessageCircle, 
  Settings, 
  Activity,
  Zap,
  Clock,
  User
} from "lucide-react";
import Link from "next/link";
import { sendMessage as sendChatMessage, getChatMessageStatus } from "@/lib/api";

interface Agent {
  id: string;
  name: string;
  description?: string;
  status: string;
  created_at?: string;
  updated_at?: string;
}

interface Message {
  id: string;
  content: string;
  role: "user" | "assistant";
  timestamp: string;
  agent_id?: string;
}

interface Props {
  agent: Agent;
}

export default function AgentDetailClient({ agent }: Props) {
  const [activeTab, setActiveTab] = useState("overview");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Load welcome message when component mounts
  useEffect(() => {
    setMessages([
      {
        id: "welcome",
        content: `Hello! I'm ${agent.name}. How can I help you today?`,
        role: "assistant",
        timestamp: new Date().toISOString(),
        agent_id: agent.id,
      },
    ]);
  }, [agent]);

  const sendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

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
      // Send to chat API
      const { data: responseData, error } = await sendChatMessage({
        content: userMessage.content,
        agent_id: agent.id,
        user_id: "frontend_user",
      });

      if (error) {
        const errorMessage: Message = {
          id: (Date.now() + 1).toString(),
          content: `Sorry, I encountered an error: ${error}`,
          role: "assistant",
          timestamp: new Date().toISOString(),
          agent_id: agent.id,
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
          agent_id: agent.id,
        };

        setMessages((prev) => [...prev, placeholderMessage]);
        
        // Start polling for the real response
        if (responseData.task_id) {
          pollForResponse(responseData.task_id);
        } else {
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
        agent_id: agent.id,
      };
      setMessages((prev) => [...prev, errorMessage]);
      setIsLoading(false);
    }
  };

  const pollForResponse = async (taskId: string) => {
    const maxPolls = 60; // Poll for up to 5 minutes
    let pollCount = 0;

    const poll = async () => {
      try {
        const { data: status, error } = await getChatMessageStatus(taskId);
        
        if (error) {
          throw new Error("Failed to check message status");
        }
        
        if (status?.status === "completed") {
          setMessages((prev) => prev.map(msg => 
            msg.id === taskId 
              ? { ...msg, content: status.content, timestamp: status.timestamp }
              : msg
          ));
          setIsLoading(false);
        } else if (status?.status === "failed") {
          setMessages((prev) => prev.map(msg => 
            msg.id === taskId 
              ? { ...msg, content: `I apologize, but I encountered an error: ${status.error || "Unknown error"}` }
              : msg
          ));
          setIsLoading(false);
        } else if (pollCount < maxPolls) {
          pollCount++;
          setTimeout(poll, 5000); // Poll every 5 seconds
        } else {
          setMessages((prev) => prev.map(msg => 
            msg.id === taskId 
              ? { ...msg, content: "Response timeout. Please try again." }
              : msg
          ));
          setIsLoading(false);
        }
      } catch (error) {
        setMessages((prev) => prev.map(msg => 
          msg.id === taskId 
            ? { ...msg, content: "Failed to get response. Please try again." }
            : msg
        ));
        setIsLoading(false);
      }
    };

    poll();
  };

  return (
    <div className="space-y-6">
      {/* Agent Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-4">
          <div className="h-16 w-16 bg-primary/10 rounded-full flex items-center justify-center">
            <Bot className="h-8 w-8 text-primary" />
          </div>
          <div>
            <div className="flex items-center gap-3">
              <h2 className="text-2xl font-bold">{agent.name}</h2>
              <Badge variant={
                agent.status === "active" ? "default" :
                agent.status === "inactive" ? "destructive" : "outline"
              }>
                {agent.status === "active" && <Zap className="h-3 w-3 mr-1" />}
                {agent.status}
              </Badge>
            </div>
            {agent.description && (
              <p className="text-muted-foreground mt-1">{agent.description}</p>
            )}
            <div className="flex items-center gap-4 mt-2 text-sm text-muted-foreground">
              {agent.created_at && (
                <div className="flex items-center gap-1">
                  <Clock className="h-4 w-4" />
                  Created {new Date(agent.created_at).toLocaleDateString()}
                </div>
              )}
            </div>
          </div>
        </div>
        <div className="flex gap-2">
          <Link href={`/agents/${agent.id}/edit`}>
            <Button variant="outline" className="gap-2">
              <Edit className="h-4 w-4" />
              Edit Agent
            </Button>
          </Link>
        </div>
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="overview" className="gap-2">
            <Settings className="h-4 w-4" />
            Overview
          </TabsTrigger>
          <TabsTrigger value="chat" className="gap-2">
            <MessageCircle className="h-4 w-4" />
            Chat
          </TabsTrigger>
          <TabsTrigger value="activity" className="gap-2">
            <Activity className="h-4 w-4" />
            Activity
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-6 mt-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <Card>
              <CardHeader>
                <CardTitle>Agent Information</CardTitle>
              </CardHeader>
              <CardContent>
                <dl className="space-y-4">
                  <div>
                    <dt className="text-sm font-medium text-muted-foreground">Name</dt>
                    <dd className="mt-1">{agent.name}</dd>
                  </div>
                  <div>
                    <dt className="text-sm font-medium text-muted-foreground">Status</dt>
                    <dd className="mt-1">
                      <Badge variant={
                        agent.status === "active" ? "default" : "destructive"
                      }>
                        {agent.status}
                      </Badge>
                    </dd>
                  </div>
                  <div>
                    <dt className="text-sm font-medium text-muted-foreground">Description</dt>
                    <dd className="mt-1">{agent.description || "No description provided"}</dd>
                  </div>
                  {agent.created_at && (
                    <div>
                      <dt className="text-sm font-medium text-muted-foreground">Created</dt>
                      <dd className="mt-1">{new Date(agent.created_at).toLocaleString()}</dd>
                    </div>
                  )}
                  {agent.updated_at && (
                    <div>
                      <dt className="text-sm font-medium text-muted-foreground">Last Updated</dt>
                      <dd className="mt-1">{new Date(agent.updated_at).toLocaleString()}</dd>
                    </div>
                  )}
                </dl>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Quick Actions</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <Button 
                  onClick={() => setActiveTab("chat")} 
                  className="w-full gap-2"
                >
                  <MessageCircle className="h-4 w-4" />
                  Start Chat Session
                </Button>
                <Link href={`/agents/${agent.id}/edit`} className="block">
                  <Button variant="outline" className="w-full gap-2">
                    <Edit className="h-4 w-4" />
                    Edit Configuration
                  </Button>
                </Link>
                <Button 
                  onClick={() => setActiveTab("activity")} 
                  variant="outline" 
                  className="w-full gap-2"
                >
                  <Activity className="h-4 w-4" />
                  View Activity Log
                </Button>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="chat" className="mt-6">
          <Card className="h-[600px] flex flex-col">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <MessageCircle className="h-5 w-5" />
                Chat with {agent.name}
              </CardTitle>
            </CardHeader>
            <CardContent className="flex-1 flex flex-col">
              {/* Messages */}
              <div className="flex-1 overflow-y-auto space-y-4 mb-4">
                {messages.map((message) => (
                  <div
                    key={message.id}
                    className={`flex gap-3 ${
                      message.role === "user" ? "justify-end" : "justify-start"
                    }`}
                  >
                    {message.role === "assistant" && (
                      <Avatar className="h-8 w-8">
                        <AvatarFallback>
                          <Bot className="h-4 w-4" />
                        </AvatarFallback>
                      </Avatar>
                    )}
                    <div
                      className={`max-w-[80%] rounded-lg px-4 py-2 ${
                        message.role === "user"
                          ? "bg-primary text-primary-foreground"
                          : "bg-muted"
                      }`}
                    >
                      <p>{message.content}</p>
                      <p className="text-xs opacity-70 mt-1">
                        {new Date(message.timestamp).toLocaleTimeString()}
                      </p>
                    </div>
                    {message.role === "user" && (
                      <Avatar className="h-8 w-8">
                        <AvatarFallback>
                          <User className="h-4 w-4" />
                        </AvatarFallback>
                      </Avatar>
                    )}
                  </div>
                ))}
                <div ref={messagesEndRef} />
              </div>

              {/* Input */}
              <form onSubmit={sendMessage} className="flex gap-2">
                <Input
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={`Message ${agent.name}...`}
                  disabled={isLoading}
                  className="flex-1"
                />
                <Button type="submit" size="icon" disabled={isLoading || !input.trim()}>
                  {isLoading ? (
                    <div className="h-4 w-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  ) : (
                    <Send className="h-4 w-4" />
                  )}
                </Button>
              </form>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="activity" className="mt-6">
          <Card>
            <CardHeader>
              <CardTitle>Activity Log</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-center py-8 text-muted-foreground">
                <Activity className="h-12 w-12 mx-auto mb-4 opacity-50" />
                <p>Activity tracking will be implemented here.</p>
                <p className="text-sm">This will show agent execution history, tasks, and interactions.</p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
} 