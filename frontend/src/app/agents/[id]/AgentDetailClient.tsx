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
  User,
  CheckCircle,
  XCircle,
  Pause,
  Play,
  Square,
  FileText,
  Calendar,
  Timer,
  AlertCircle
} from "lucide-react";
import Link from "next/link";
import { 
  createAgentTask,
  listAgentTasks,
  getAgentTaskStatus,
  pauseAgentTask,
  resumeAgentTask,
  cancelAgentTask
} from "@/lib/api";

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

interface Task {
  id: string;
  description: string;
  status: "pending" | "running" | "completed" | "failed" | "paused" | "cancelled";
  created_at: string;
  updated_at?: string;
  agent_id: string;
  agent_name?: string;
}

interface TaskStatus {
  status: string;
  task_id: string;
  agent_id: string;
  start_time?: string;
  end_time?: string;
  execution_time?: string;
  message?: string;
  error?: string;
  artifacts?: Array<{
    name: string;
    type: string;
    content?: string;
  }>;
  usage_metadata?: any;
  session_id?: string;
}

interface Props {
  agent: Agent;
}

const getStatusVariant = (status: string) => {
  switch (status) {
    case "completed":
      return "default";
    case "running":
      return "secondary";
    case "failed":
      return "destructive";
    case "paused":
      return "outline";
    case "cancelled":
      return "secondary";
    default:
      return "secondary";
  }
};

export default function AgentDetailClient({ agent }: Props) {
  // Start with chat tab open by default
  const [activeTab, setActiveTab] = useState("chat");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [taskStatuses, setTaskStatuses] = useState<Record<string, TaskStatus>>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Focus input when chat tab is activated
  useEffect(() => {
    if (activeTab === "chat" && inputRef.current) {
      setTimeout(() => {
        inputRef.current?.focus();
      }, 100);
    }
  }, [activeTab]);

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

  // Load tasks when component mounts or when tasks tab is activated
  useEffect(() => {
    if (activeTab === "tasks") {
      loadTasks();
    }
  }, [activeTab, agent.id]);

  const loadTasks = async () => {
    setTasksLoading(true);
    try {
      const { data: tasksData, error } = await listAgentTasks(agent.id);
      if (!error && tasksData) {
        setTasks(tasksData);
        // Load status for each task
        for (const task of tasksData) {
          loadTaskStatus(task.id);
        }
      }
    } catch (error) {
      console.error("Failed to load tasks:", error);
    } finally {
      setTasksLoading(false);
    }
  };

  const loadTaskStatus = async (taskId: string) => {
    try {
      const { data: statusData, error } = await getAgentTaskStatus(agent.id, taskId);
      if (!error && statusData) {
        setTaskStatuses(prev => ({
          ...prev,
          [taskId]: statusData as TaskStatus
        }));
      }
    } catch (error) {
      console.error(`Failed to load status for task ${taskId}:`, error);
    }
  };

  const handleTaskAction = async (taskId: string, action: "pause" | "resume" | "cancel") => {
    try {
      let result;
      switch (action) {
        case "pause":
          result = await pauseAgentTask(agent.id, taskId);
          break;
        case "resume":
          result = await resumeAgentTask(agent.id, taskId);
          break;
        case "cancel":
          result = await cancelAgentTask(agent.id, taskId);
          break;
      }
      
      if (!result.error) {
        // Refresh task status
        loadTaskStatus(taskId);
        // Refresh task list
        loadTasks();
      }
    } catch (error) {
      console.error(`Failed to ${action} task:`, error);
    }
  };

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
      let assistantMessage: Message | null = null;

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
                console.log('SSE Event:', eventData);

                if (eventData.type === 'connected') {
                  // Task creation started
                  console.log('Connected to task stream');
                } else if (eventData.type === 'task_created') {
                  // Task was created, add placeholder message
                  assistantMessage = {
                    id: eventData.data.task_id,
                    content: "🤔 Thinking...",
                    role: "assistant",
                    timestamp: eventData.data.timestamp || new Date().toISOString(),
                    agent_id: agent.id,
                  };
                  setMessages((prev) => [...prev, assistantMessage!]);
                  // Refresh tasks if tasks tab is active
                  if (activeTab === "tasks") {
                    loadTasks();
                  }
                } else if (eventData.type === 'task_completed' || eventData.type === 'workflow_completed') {
                  // Task completed, update message with result
                  const result = eventData.data.result || eventData.data.content || eventData.data.message;
                  if (assistantMessage) {
                    setMessages((prev) => prev.map(msg => 
                      msg.id === assistantMessage!.id 
                        ? { 
                            ...msg, 
                            content: result || "Task completed successfully",
                            timestamp: eventData.data.timestamp || new Date().toISOString()
                          }
                        : msg
                    ));
                  }
                  setIsLoading(false);
                  // Refresh tasks if tasks tab is active
                  if (activeTab === "tasks") {
                    loadTasks();
                  }
                  break;
                } else if (eventData.type === 'task_failed' || eventData.type === 'workflow_failed') {
                  // Task failed, update message with error
                  const error = eventData.data.error || eventData.data.message || "Unknown error";
                  if (assistantMessage) {
                    setMessages((prev) => prev.map(msg => 
                      msg.id === assistantMessage!.id 
                        ? { 
                            ...msg, 
                            content: `I apologize, but I encountered an error: ${error}`,
                            timestamp: eventData.data.timestamp || new Date().toISOString()
                          }
                        : msg
                    ));
                  }
                  setIsLoading(false);
                  // Refresh tasks if tasks tab is active
                  if (activeTab === "tasks") {
                    loadTasks();
                  }
                  break;
                } else if (eventData.type === 'error') {
                  // Stream error
                  const error = eventData.data.error || "Stream error";
                  if (assistantMessage) {
                    setMessages((prev) => prev.map(msg => 
                      msg.id === assistantMessage!.id 
                        ? { 
                            ...msg, 
                            content: `I apologize, but I encountered an error: ${error}`,
                            timestamp: eventData.data.timestamp || new Date().toISOString()
                          }
                        : msg
                    ));
                  }
                  setIsLoading(false);
                  break;
                }
              } catch (parseError) {
                console.error('Failed to parse SSE event:', parseError);
              }
            }
          }
        }
      } finally {
        reader.releaseLock();
      }

      // If we get here and still loading, something went wrong
      if (isLoading) {
        setIsLoading(false);
        if (assistantMessage) {
          setMessages((prev) => prev.map(msg => 
            msg.id === assistantMessage!.id 
              ? { 
                  ...msg, 
                  content: "Response timeout. Please try again.",
                  timestamp: new Date().toISOString()
                }
              : msg
          ));
        }
      }

    } catch (error) {
      console.error('Failed to send message:', error);
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



  return (
    <div className="space-y-6">
      {/* Agent Header */}
      <div className="flex items-start justify-between p-6 bg-gradient-to-r from-background via-muted/20 to-background rounded-lg border shadow-sm">
        <div className="flex items-center gap-4">
          <div className="h-16 w-16 bg-gradient-to-br from-primary/20 to-primary/10 rounded-full flex items-center justify-center shadow-sm border border-primary/20">
            <Bot className="h-8 w-8 text-primary" />
          </div>
          <div>
            <div className="flex items-center gap-3 mb-1">
              <h2 className="text-2xl font-bold bg-gradient-to-r from-foreground to-foreground/80 bg-clip-text">
                {agent.name}
              </h2>
              <Badge 
                variant={
                  agent.status === "active" ? "default" :
                  agent.status === "inactive" ? "destructive" : "outline"
                }
                className="gap-1 shadow-sm"
              >
                {agent.status === "active" && <Zap className="h-3 w-3" />}
                {agent.status}
              </Badge>
            </div>
            {agent.description && (
              <p className="text-muted-foreground mt-1 leading-relaxed max-w-md">
                {agent.description}
              </p>
            )}
            <div className="flex items-center gap-4 mt-3 text-sm text-muted-foreground">
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
            <Button 
              variant="outline" 
              className="gap-2 shadow-sm hover:shadow-md transition-all duration-200"
            >
              <Edit className="h-4 w-4" />
              Edit Agent
            </Button>
          </Link>
        </div>
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
        <TabsList className="grid w-full grid-cols-4 bg-muted/50 p-1 rounded-lg">
          <TabsTrigger 
            value="chat" 
            className="gap-2 data-[state=active]:bg-background data-[state=active]:shadow-sm transition-all duration-200"
          >
            <MessageCircle className="h-4 w-4" />
            Chat
          </TabsTrigger>
          <TabsTrigger 
            value="tasks" 
            className="gap-2 data-[state=active]:bg-background data-[state=active]:shadow-sm transition-all duration-200"
          >
            <CheckCircle className="h-4 w-4" />
            Tasks
          </TabsTrigger>
          <TabsTrigger 
            value="overview" 
            className="gap-2 data-[state=active]:bg-background data-[state=active]:shadow-sm transition-all duration-200"
          >
            <Settings className="h-4 w-4" />
            Overview
          </TabsTrigger>
          <TabsTrigger 
            value="activity" 
            className="gap-2 data-[state=active]:bg-background data-[state=active]:shadow-sm transition-all duration-200"
          >
            <Activity className="h-4 w-4" />
            Activity
          </TabsTrigger>
        </TabsList>

        <TabsContent value="chat" className="mt-6">
          <Card className="h-[600px] flex flex-col shadow-sm border-0 bg-gradient-to-b from-background to-muted/20">
            <CardHeader className="border-b bg-background/50 backdrop-blur-sm">
              <CardTitle className="flex items-center gap-2">
                <MessageCircle className="h-5 w-5 text-primary" />
                Chat with {agent.name}
              </CardTitle>
            </CardHeader>
            <CardContent className="flex-1 flex flex-col p-0">
              {/* Messages */}
              <div className="flex-1 overflow-y-auto space-y-4 p-4">
                {messages.map((message) => (
                  <div
                    key={message.id}
                    className={`flex gap-3 animate-in slide-in-from-bottom-2 duration-300 ${
                      message.role === "user" ? "justify-end" : "justify-start"
                    }`}
                  >
                    {message.role === "assistant" && (
                      <Avatar className="h-8 w-8 border-2 border-primary/20">
                        <AvatarFallback className="bg-primary/10">
                          <Bot className="h-4 w-4 text-primary" />
                        </AvatarFallback>
                      </Avatar>
                    )}
                    <div
                      className={`max-w-[80%] rounded-2xl px-4 py-3 shadow-sm transition-all duration-200 hover:shadow-md ${
                        message.role === "user"
                          ? "bg-primary text-primary-foreground"
                          : "bg-background border border-border"
                      }`}
                    >
                      <p className="text-sm leading-relaxed">{message.content}</p>
                      <p className="text-xs opacity-70 mt-2">
                        {new Date(message.timestamp).toLocaleTimeString()}
                      </p>
                    </div>
                    {message.role === "user" && (
                      <Avatar className="h-8 w-8 border-2 border-muted">
                        <AvatarFallback className="bg-muted">
                          <User className="h-4 w-4" />
                        </AvatarFallback>
                      </Avatar>
                    )}
                  </div>
                ))}
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
        </TabsContent>

        <TabsContent value="tasks" className="mt-6">
          <Card className="shadow-sm border-0">
            <CardHeader className="bg-gradient-to-r from-background to-muted/20">
              <div className="flex items-center justify-between">
                <CardTitle className="flex items-center gap-2">
                  <CheckCircle className="h-5 w-5 text-primary" />
                  Agent Tasks
                </CardTitle>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={loadTasks}
                  disabled={tasksLoading}
                  className="gap-2"
                >
                  {tasksLoading ? (
                    <div className="h-4 w-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                  ) : (
                    <Activity className="h-4 w-4" />
                  )}
                  Refresh
                </Button>
              </div>
            </CardHeader>
            <CardContent className="p-6">
              {tasksLoading ? (
                <div className="flex items-center justify-center py-12">
                  <div className="flex items-center gap-3">
                    <div className="h-6 w-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                    <span className="text-muted-foreground">Loading tasks...</span>
                  </div>
                </div>
              ) : tasks.length === 0 ? (
                <div className="text-center py-12">
                  <CheckCircle className="h-16 w-16 mx-auto mb-4 text-muted-foreground/50" />
                  <h3 className="text-lg font-medium mb-2">No tasks yet</h3>
                  <p className="text-muted-foreground mb-4">
                    This agent hasn't been assigned any tasks yet.
                  </p>
                  <Button 
                    onClick={() => setActiveTab("chat")}
                    className="gap-2"
                  >
                    <MessageCircle className="h-4 w-4" />
                    Start a conversation
                  </Button>
                </div>
              ) : (
                <div className="space-y-4">
                  {tasks.map((task) => {
                    const status = taskStatuses[task.id];
                    const isActive = ["running", "paused"].includes(task.status);
                    
                    return (
                      <div
                        key={task.id}
                        className="border rounded-lg p-4 hover:shadow-md transition-all duration-200 bg-gradient-to-r from-background to-muted/10"
                      >
                        <div className="flex items-start justify-between">
                          <div className="flex-1">
                            <div className="flex items-center gap-3 mb-2">
                              <Badge 
                                variant={getStatusVariant(task.status)}
                                className="gap-1"
                              >
                                {task.status === "completed" && <CheckCircle className="h-3 w-3" />}
                                {task.status === "running" && <Timer className="h-3 w-3" />}
                                {task.status === "failed" && <XCircle className="h-3 w-3" />}
                                {task.status === "paused" && <Pause className="h-3 w-3" />}
                                {task.status}
                              </Badge>
                              <span className="text-sm text-muted-foreground">
                                {new Date(task.created_at).toLocaleString()}
                              </span>
                            </div>
                            <p className="font-medium mb-1">{task.description}</p>
                            {status?.message && (
                              <p className="text-sm text-muted-foreground mb-2">
                                {status.message}
                              </p>
                            )}
                            {status?.error && (
                              <div className="flex items-center gap-2 text-sm text-destructive mb-2">
                                <AlertCircle className="h-4 w-4" />
                                {status.error}
                              </div>
                            )}
                            <div className="flex items-center gap-4 text-xs text-muted-foreground">
                              <div className="flex items-center gap-1">
                                <Calendar className="h-3 w-3" />
                                ID: {task.id.slice(0, 8)}...
                              </div>
                              {status?.execution_time && (
                                <div className="flex items-center gap-1">
                                  <Clock className="h-3 w-3" />
                                  {status.execution_time}
                                </div>
                              )}
                              {status?.artifacts && status.artifacts.length > 0 && (
                                <div className="flex items-center gap-1">
                                  <FileText className="h-3 w-3" />
                                  {status.artifacts.length} artifacts
                                </div>
                              )}
                            </div>
                          </div>
                          <div className="flex gap-2 ml-4">
                            {task.status === "running" && (
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => handleTaskAction(task.id, "pause")}
                                className="gap-1"
                              >
                                <Pause className="h-3 w-3" />
                                Pause
                              </Button>
                            )}
                            {task.status === "paused" && (
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => handleTaskAction(task.id, "resume")}
                                className="gap-1"
                              >
                                <Play className="h-3 w-3" />
                                Resume
                              </Button>
                            )}
                            {isActive && (
                              <Button
                                size="sm"
                                variant="destructive"
                                onClick={() => handleTaskAction(task.id, "cancel")}
                                className="gap-1"
                              >
                                <Square className="h-3 w-3" />
                                Cancel
                              </Button>
                            )}
                            <Link href={`/tasks/${task.id}`}>
                              <Button size="sm" variant="ghost" className="gap-1">
                                <FileText className="h-3 w-3" />
                                Details
                              </Button>
                            </Link>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="overview" className="space-y-6 mt-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <Card className="shadow-sm border-0 bg-gradient-to-br from-background to-muted/20">
              <CardHeader className="bg-gradient-to-r from-background to-muted/20">
                <CardTitle className="flex items-center gap-2">
                  <Settings className="h-5 w-5 text-primary" />
                  Agent Information
                </CardTitle>
              </CardHeader>
              <CardContent className="p-6">
                <dl className="space-y-4">
                  <div className="group">
                    <dt className="text-sm font-medium text-muted-foreground mb-1">Name</dt>
                    <dd className="font-medium">{agent.name}</dd>
                  </div>
                  <div className="group">
                    <dt className="text-sm font-medium text-muted-foreground mb-1">Status</dt>
                    <dd>
                      <Badge 
                        variant={agent.status === "active" ? "default" : "destructive"}
                        className="gap-1"
                      >
                        {agent.status === "active" && <Zap className="h-3 w-3" />}
                        {agent.status}
                      </Badge>
                    </dd>
                  </div>
                  <div className="group">
                    <dt className="text-sm font-medium text-muted-foreground mb-1">Description</dt>
                    <dd className="text-sm leading-relaxed">{agent.description || "No description provided"}</dd>
                  </div>
                  {agent.created_at && (
                    <div className="group">
                      <dt className="text-sm font-medium text-muted-foreground mb-1">Created</dt>
                      <dd className="text-sm flex items-center gap-2">
                        <Calendar className="h-4 w-4 text-muted-foreground" />
                        {new Date(agent.created_at).toLocaleString()}
                      </dd>
                    </div>
                  )}
                  {agent.updated_at && (
                    <div className="group">
                      <dt className="text-sm font-medium text-muted-foreground mb-1">Last Updated</dt>
                      <dd className="text-sm flex items-center gap-2">
                        <Clock className="h-4 w-4 text-muted-foreground" />
                        {new Date(agent.updated_at).toLocaleString()}
                      </dd>
                    </div>
                  )}
                </dl>
              </CardContent>
            </Card>

            <Card className="shadow-sm border-0 bg-gradient-to-br from-background to-muted/20">
              <CardHeader className="bg-gradient-to-r from-background to-muted/20">
                <CardTitle className="flex items-center gap-2">
                  <Zap className="h-5 w-5 text-primary" />
                  Quick Actions
                </CardTitle>
              </CardHeader>
              <CardContent className="p-6 space-y-3">
                <Button 
                  onClick={() => setActiveTab("chat")} 
                  className="w-full gap-2 shadow-sm hover:shadow-md transition-all duration-200"
                >
                  <MessageCircle className="h-4 w-4" />
                  Start Chat Session
                </Button>
                <Button 
                  onClick={() => setActiveTab("tasks")} 
                  variant="outline" 
                  className="w-full gap-2 hover:bg-muted/50 transition-all duration-200"
                >
                  <CheckCircle className="h-4 w-4" />
                  View Tasks
                </Button>
                <Link href={`/agents/${agent.id}/edit`} className="block">
                  <Button 
                    variant="outline" 
                    className="w-full gap-2 hover:bg-muted/50 transition-all duration-200"
                  >
                    <Edit className="h-4 w-4" />
                    Edit Configuration
                  </Button>
                </Link>
                <Button 
                  onClick={() => setActiveTab("activity")} 
                  variant="outline" 
                  className="w-full gap-2 hover:bg-muted/50 transition-all duration-200"
                >
                  <Activity className="h-4 w-4" />
                  View Activity Log
                </Button>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="activity" className="mt-6">
          <Card className="shadow-sm border-0">
            <CardHeader className="bg-gradient-to-r from-background to-muted/20">
              <CardTitle className="flex items-center gap-2">
                <Activity className="h-5 w-5 text-primary" />
                Activity Log
              </CardTitle>
            </CardHeader>
            <CardContent className="p-6">
              <div className="text-center py-12">
                <Activity className="h-16 w-16 mx-auto mb-4 text-muted-foreground/50" />
                <h3 className="text-lg font-medium mb-2">Activity tracking coming soon</h3>
                <p className="text-muted-foreground mb-4">
                  This will show agent execution history, tasks, and interactions.
                </p>
                <div className="flex gap-2 justify-center">
                  <Button 
                    onClick={() => setActiveTab("chat")}
                    variant="outline"
                    className="gap-2"
                  >
                    <MessageCircle className="h-4 w-4" />
                    Start chatting
                  </Button>
                  <Button 
                    onClick={() => setActiveTab("tasks")}
                    variant="outline"
                    className="gap-2"
                  >
                    <CheckCircle className="h-4 w-4" />
                    View tasks
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
} 