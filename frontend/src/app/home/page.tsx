"use client";

import React, { useState } from "react";
import { Card } from "@/components/ui/card";
import { Bot, Database, Code2, Activity, MessageSquare, Send } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import Link from "next/link";

interface Message {
  id: string;
  content: string;
  sender: "user" | "agent";
  timestamp: Date;
}

interface StatCardProps {
  title: string;
  value: string;
  icon: React.ReactNode;
  description: string;
}

const StatCard = ({ title, value, icon, description }: StatCardProps) => (
  <Card className="p-6">
    <div className="flex items-center justify-between">
      <div>
        <p className="text-sm font-medium text-muted-foreground">{title}</p>
        <h3 className="text-2xl font-bold mt-2">{value}</h3>
      </div>
      <div className="h-12 w-12 bg-primary/10 rounded-full flex items-center justify-center">
        {icon}
      </div>
    </div>
    <p className="text-sm text-muted-foreground mt-2">{description}</p>
  </Card>
);

export default function HomePage() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "1",
      content: "Hello! I'm your AgentArea assistant. How can I help you today?",
      sender: "agent",
      timestamp: new Date(),
    },
  ]);
  const [inputValue, setInputValue] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handleSendMessage = async () => {
    if (!inputValue.trim() || isLoading) return;
    
    // Add user message
    const userMessage: Message = {
      id: Date.now().toString(),
      content: inputValue,
      sender: "user",
      timestamp: new Date(),
    };
    
    setMessages((prev) => [...prev, userMessage]);
    const messageContent = inputValue;
    setInputValue("");
    setIsLoading(true);
    
    try {
      // Get available agents first
      const agentsResponse = await fetch('/api/v1/chat/agents');
      const agents = await agentsResponse.json();
      
      if (agents.length === 0) {
        throw new Error('No agents available');
      }
      
      // Send message to first available agent
      const response = await fetch('/api/v1/chat/messages', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: messageContent,
          agent_id: agents[0].id,
          user_id: 'home_user',
          session_id: 'home_session',
        }),
      });
      
      if (!response.ok) {
        throw new Error('Failed to send message');
      }
      
      const result = await response.json();
      
      // Add agent response
      const agentMessage: Message = {
        id: result.task_id || (Date.now() + 1).toString(),
        content: result.content || "Message received and processing...",
        sender: "agent",
        timestamp: new Date(),
      };
      
      setMessages((prev) => [...prev, agentMessage]);
      
    } catch (error) {
      console.error('Error sending message:', error);
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        content: `Sorry, I couldn't process your message. Error: ${error}`,
        sender: "agent",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-4xl font-bold">Welcome to AgentMesh</h1>
        <p className="text-lg text-muted-foreground mt-2">
          Your central hub for deploying, managing, and orchestrating automation agents
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <StatCard
          title="Active Agents"
          value="12"
          icon={<Bot className="h-6 w-6 text-primary" />}
          description="Currently running automation agents"
        />
        <StatCard
          title="Data Sources"
          value="8"
          icon={<Database className="h-6 w-6 text-primary" />}
          description="Connected data sources and integrations"
        />
        <StatCard
          title="Tasks"
          value="5"
          icon={<Code2 className="h-6 w-6 text-primary" />}
          description="Active automation tasks"
        />
        <StatCard
          title="Tasks Today"
          value="156"
          icon={<Activity className="h-6 w-6 text-primary" />}
          description="Tasks completed in the last 24 hours"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
        <div className="lg:col-span-2">
          <Card className="p-6">
            <div className="flex items-center mb-4">
              <MessageSquare className="h-5 w-5 text-primary mr-2" />
              <h2 className="text-xl font-semibold">Agent Chat</h2>
            </div>
            
            <ScrollArea className="h-[400px] pr-4 mb-4">
              <div className="space-y-4">
                {messages.map((message) => (
                  <div 
                    key={message.id} 
                    className={`flex ${message.sender === 'user' ? 'justify-end' : 'justify-start'}`}
                  >
                    <div 
                      className={`max-w-[80%] p-3 rounded-lg ${
                        message.sender === 'user' 
                          ? 'bg-primary text-primary-foreground' 
                          : 'bg-secondary'
                      }`}
                    >
                      <p>{message.content}</p>
                      <p className="text-xs opacity-70 mt-1">
                        {message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </ScrollArea>
            
            <div className="flex items-center space-x-2">
              <Input
                placeholder="Type your task or question here..."
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
                className="flex-1"
              />
              <Button onClick={handleSendMessage} size="icon" disabled={isLoading}>
                {isLoading ? <div className="h-4 w-4 border-2 border-white border-t-transparent rounded-full animate-spin" /> : <Send className="h-4 w-4" />}
              </Button>
            </div>
          </Card>
        </div>

        <div>
          <Card className="p-6">
            <h2 className="text-xl font-semibold mb-4">Quick Actions</h2>
            <div className="space-y-4">
              <button className="w-full text-left px-4 py-3 rounded-lg hover:bg-secondary transition-colors">
                <span className="font-medium">Deploy New Agent</span>
                <p className="text-sm text-muted-foreground">Create and deploy a new automation agent</p>
              </button>
              <button className="w-full text-left px-4 py-3 rounded-lg hover:bg-secondary transition-colors">
                <span className="font-medium">Connect Data Source</span>
                <p className="text-sm text-muted-foreground">Add a new data source or integration</p>
              </button>
              <button className="w-full text-left px-4 py-3 rounded-lg hover:bg-secondary transition-colors">
                <span className="font-medium">Create Workflow</span>
                <p className="text-sm text-muted-foreground">Build a new automation workflow</p>
              </button>
              <Link href="/home/chat" className="block">
                <div className="w-full text-left px-4 py-3 rounded-lg hover:bg-secondary transition-colors">
                  <div className="flex items-center">
                    <MessageSquare className="h-5 w-5 text-primary mr-2" />
                    <span className="font-medium">Open Agent Chat</span>
                  </div>
                  <p className="text-sm text-muted-foreground">Interact with agents through our advanced chat interface</p>
                </div>
              </Link>
            </div>
          </Card>
        </div>
      </div>

      <Card className="p-6">
        <h2 className="text-xl font-semibold mb-4">Recent Activity</h2>
        <div className="space-y-4">
          {[
            {
              title: "Inventory Monitor Agent",
              description: "Alert: Low stock detected for SKU-123",
              time: "10 minutes ago"
            },
            {
              title: "Customer Support Agent",
              description: "Processed 25 support tickets",
              time: "1 hour ago"
            },
            {
              title: "Analytics Workflow",
              description: "Generated daily marketing report",
              time: "2 hours ago"
            }
          ].map((activity, index) => (
            <div key={index} className="flex items-start space-x-4 p-3 rounded-lg hover:bg-secondary transition-colors">
              <div className="flex-1">
                <p className="font-medium">{activity.title}</p>
                <p className="text-sm text-muted-foreground">{activity.description}</p>
              </div>
              <span className="text-xs text-muted-foreground">{activity.time}</span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}