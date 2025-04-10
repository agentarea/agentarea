"use client";

import React, { useState, useRef, useEffect } from "react";
import { Card } from "@/components/ui/card";
import { 
  Bot, 
  Database, 
  ClipboardList, 
  MessageSquare, 
  Send, 
  Bell, 
  CheckCircle2, 
  Clock,
  AlertCircle,
  Filter,
  X,
  Plus,
  ChevronRight,
  Building2,
  Wrench,
  Server
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface Message {
  id: string;
  content: string;
  sender: "user" | "agent";
  timestamp: Date;
}

interface Notification {
  id: string;
  title: string;
  message: string;
  type: "info" | "warning" | "error";
  time: string;
  isRead: boolean;
}

interface Task {
  id: string;
  title: string;
  description: string;
  status: "pending" | "in_progress" | "needs_input" | "completed";
  priority: "low" | "medium" | "high";
  assignedAgent: string;
  createdAt: string;
}

interface WorkplaceResource {
  id: string;
  name: string;
  type: "agent" | "source" | "tool" | "mcp";
  description: string;
  status: "active" | "inactive";
}

interface Mention {
  id: string;
  name: string;
  type: "agent" | "source" | "tool" | "mcp";
  icon: React.ReactNode;
  color: string;
}

export default function WorkplacePage() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "1",
      content: "Hello! I'm your AgentMesh assistant. What tasks can I help you with today?",
      sender: "agent",
      timestamp: new Date(),
    },
  ]);
  const [inputValue, setInputValue] = useState("");
  const [taskFilter, setTaskFilter] = useState<string>("all");
  const [activeTab, setActiveTab] = useState<string>("chat");
  const [selectedWorkplace, setSelectedWorkplace] = useState<string>("personal");
  const [showMentionSelector, setShowMentionSelector] = useState(false);
  const [mentionQuery, setMentionQuery] = useState("");
  const [cursorPosition, setCursorPosition] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  
  const getResourceIcon = (type: WorkplaceResource["type"]) => {
    switch(type) {
      case "agent": return <Bot className="h-4 w-4" />;
      case "source": return <Database className="h-4 w-4" />;
      case "tool": return <Wrench className="h-4 w-4" />;
      case "mcp": return <Server className="h-4 w-4" />;
    }
  };

  const getResourceColor = (type: WorkplaceResource["type"]) => {
    switch(type) {
      case "agent": return "text-blue-500";
      case "source": return "text-green-500";
      case "tool": return "text-purple-500";
      case "mcp": return "text-orange-500";
    }
  };
  
  // Sample workplaces data
  const workplaces = [
    { id: "personal", name: "Personal Workspace", icon: <Building2 className="h-4 w-4" /> },
    { id: "team1", name: "Marketing Team", icon: <Building2 className="h-4 w-4" /> },
    { id: "team2", name: "Development Team", icon: <Building2 className="h-4 w-4" /> },
    { id: "team3", name: "Sales Team", icon: <Building2 className="h-4 w-4" /> },
  ];
  
  // Sample data for tasks and notifications
  const [tasks, setTasks] = useState<Task[]>([
    {
      id: "task-1",
      title: "Analyze Q1 Sales Data",
      description: "Generate insights from Q1 sales data and create a summary report",
      status: "in_progress",
      priority: "high",
      assignedAgent: "Data Analytics Agent",
      createdAt: "2 hours ago"
    },
    {
      id: "task-2",
      title: "Update Customer FAQ",
      description: "Refresh the FAQ section with latest product information",
      status: "needs_input",
      priority: "medium",
      assignedAgent: "Content Management Agent",
      createdAt: "5 hours ago"
    },
    {
      id: "task-3",
      title: "Monitor Website Performance",
      description: "Track website metrics and alert on any performance issues",
      status: "pending",
      priority: "medium",
      assignedAgent: "Monitoring Agent",
      createdAt: "1 day ago"
    },
    {
      id: "task-4",
      title: "Generate Weekly Analytics Report",
      description: "Prepare the standard weekly analytics report for distribution",
      status: "completed",
      priority: "high",
      assignedAgent: "Reporting Agent",
      createdAt: "2 days ago"
    }
  ]);
  
  const [notifications, setNotifications] = useState<Notification[]>([
    {
      id: "notif-1",
      title: "Task Requires Input",
      message: "The Content Management Agent needs your input on FAQ updates",
      type: "warning",
      time: "30 minutes ago",
      isRead: false
    },
    {
      id: "notif-2",
      title: "Analysis Complete",
      message: "Weekly summary report has been generated and is ready for review",
      type: "info",
      time: "2 hours ago",
      isRead: false
    },
    {
      id: "notif-3",
      title: "System Alert",
      message: "Database connection issues detected. Some agents may experience delays",
      type: "error",
      time: "3 hours ago",
      isRead: true
    }
  ]);

  // Sample workplace resources data
  const workplaceResources: Record<string, WorkplaceResource[]> = {
    personal: [
      {
        id: "agent-1",
        name: "Personal Assistant",
        type: "agent",
        description: "Your personal AI assistant",
        status: "active"
      },
      {
        id: "source-1",
        name: "Personal Calendar",
        type: "source",
        description: "Your calendar data",
        status: "active"
      }
    ],
    team1: [
      {
        id: "agent-2",
        name: "Marketing Analytics Agent",
        type: "agent",
        description: "Analyzes marketing data and trends",
        status: "active"
      },
      {
        id: "tool-1",
        name: "Social Media Manager",
        type: "tool",
        description: "Manages social media posts and engagement",
        status: "active"
      },
      {
        id: "mcp-1",
        name: "Marketing MCP",
        type: "mcp",
        description: "Marketing team's MCP server",
        status: "active"
      }
    ],
    team2: [
      {
        id: "agent-3",
        name: "Code Review Agent",
        type: "agent",
        description: "Reviews and analyzes code changes",
        status: "active"
      },
      {
        id: "tool-2",
        name: "GitHub Integration",
        type: "tool",
        description: "GitHub repository management",
        status: "active"
      }
    ],
    team3: [
      {
        id: "agent-4",
        name: "Sales Analytics Agent",
        type: "agent",
        description: "Analyzes sales data and forecasts",
        status: "active"
      },
      {
        id: "source-2",
        name: "CRM Database",
        type: "source",
        description: "Customer relationship management data",
        status: "active"
      }
    ]
  };

  // Get all resources for current workplace
  const currentResources = workplaceResources[selectedWorkplace] || [];
  
  // Convert resources to mentions format
  const mentions: Mention[] = currentResources.map(resource => ({
    id: resource.id,
    name: resource.name,
    type: resource.type,
    icon: getResourceIcon(resource.type),
    color: getResourceColor(resource.type)
  }));

  // Filter mentions based on query
  const filteredMentions = mentions.filter(mention => 
    mention.name.toLowerCase().includes(mentionQuery.toLowerCase())
  );

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    const position = e.target.selectionStart || 0;
    
    setInputValue(value);
    setCursorPosition(position);

    // Check if we should show mention selector
    const lastAtSymbol = value.lastIndexOf('@', position);
    if (lastAtSymbol !== -1) {
      const query = value.slice(lastAtSymbol + 1, position);
      setMentionQuery(query);
      setShowMentionSelector(true);
    } else {
      setShowMentionSelector(false);
    }
  };

  const handleMentionSelect = (mention: Mention) => {
    const beforeMention = inputValue.slice(0, cursorPosition);
    const afterMention = inputValue.slice(cursorPosition);
    const lastAtSymbol = beforeMention.lastIndexOf('@');
    
    const newValue = beforeMention.slice(0, lastAtSymbol) + 
      `@${mention.name} ` + 
      afterMention;
    
    setInputValue(newValue);
    setShowMentionSelector(false);
    inputRef.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!showMentionSelector) return;

    if (e.key === 'Escape') {
      setShowMentionSelector(false);
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      // Handle arrow navigation in mention selector
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (filteredMentions.length > 0) {
        handleMentionSelect(filteredMentions[0]);
      }
    }
  };

  const handleSendMessage = () => {
    if (!inputValue.trim()) return;
    
    // Add user message
    const userMessage: Message = {
      id: Date.now().toString(),
      content: inputValue,
      sender: "user",
      timestamp: new Date(),
    };
    
    setMessages((prev) => [...prev, userMessage]);
    setInputValue("");
    
    // Simulate agent response
    setTimeout(() => {
      const agentMessage: Message = {
        id: (Date.now() + 1).toString(),
        content: `I'll help you with "${inputValue}". I'll set up the task and assign it to the appropriate agent.`,
        sender: "agent",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, agentMessage]);
    }, 1000);
  };

  const markNotificationAsRead = (id: string) => {
    setNotifications(notifications.map(notif => 
      notif.id === id ? { ...notif, isRead: true } : notif
    ));
  };

  const unreadCount = notifications.filter(n => !n.isRead).length;
  
  const filteredTasks = taskFilter === "all" 
    ? tasks 
    : tasks.filter(task => task.status === taskFilter);

  const getPriorityColor = (priority: string) => {
    switch(priority) {
      case 'high': return 'text-red-500';
      case 'medium': return 'text-amber-500';
      case 'low': return 'text-green-500';
      default: return 'text-blue-500';
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-background to-muted/20">
      <div className="p-8 max-w-7xl mx-auto">
        <div className="mb-12">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-4xl font-bold tracking-tight bg-gradient-to-r from-primary to-primary/60 bg-clip-text text-transparent">
                Workplace
              </h1>
              <p className="text-lg text-muted-foreground mt-2">
                Your command center for managing agents, tasks, and notifications
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Select value={selectedWorkplace} onValueChange={setSelectedWorkplace}>
                <SelectTrigger className="w-[200px] h-9 text-sm bg-background">
                  <SelectValue placeholder="Select workplace" />
                </SelectTrigger>
                <SelectContent>
                  {workplaces.map((workplace) => (
                    <SelectItem key={workplace.id} value={workplace.id}>
                      <div className="flex items-center gap-2">
                        {workplace.icon}
                        {workplace.name}
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button size="icon" variant="outline" className="h-9 w-9">
                <Plus className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
          <div className="lg:col-span-8">
            <Tabs 
              defaultValue="chat" 
              className="w-full"
              value={activeTab}
              onValueChange={setActiveTab}
            >
              <div className="flex justify-between items-center mb-6">
                <TabsList className="grid w-full max-w-md grid-cols-3 bg-muted/50 p-1">
                  <TabsTrigger value="chat" className="rounded-md data-[state=active]:bg-background data-[state=active]:shadow-sm">
                    <div className="flex items-center gap-2">
                      <MessageSquare className="h-4 w-4" />
                      <span>Chat</span>
                    </div>
                  </TabsTrigger>
                  <TabsTrigger value="tasks" className="rounded-md data-[state=active]:bg-background data-[state=active]:shadow-sm">
                    <div className="flex items-center gap-2">
                      <ClipboardList className="h-4 w-4" />
                      <span>Tasks</span>
                    </div>
                  </TabsTrigger>
                  <TabsTrigger value="notifications" className="rounded-md data-[state=active]:bg-background data-[state=active]:shadow-sm">
                    <div className="flex items-center gap-2">
                      <Bell className="h-4 w-4" />
                      <span>Notifications</span>
                      {unreadCount > 0 && (
                        <Badge variant="destructive" className="ml-1">{unreadCount}</Badge>
                      )}
                    </div>
                  </TabsTrigger>
                </TabsList>
                
                {activeTab === "tasks" && (
                  <div className="flex items-center gap-2">
                    <Select value={taskFilter} onValueChange={setTaskFilter}>
                      <SelectTrigger className="w-[180px] h-9 text-sm bg-background">
                        <SelectValue placeholder="Filter by status" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All Tasks</SelectItem>
                        <SelectItem value="pending">Pending</SelectItem>
                        <SelectItem value="in_progress">In Progress</SelectItem>
                        <SelectItem value="needs_input">Needs Input</SelectItem>
                        <SelectItem value="completed">Completed</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                )}
              </div>
              
              <TabsContent value="chat" className="mt-0">
                <Card className="p-6 border-none shadow-lg bg-gradient-to-b from-background to-muted/20">
                  <ScrollArea className="h-[450px] pr-4 mb-4">
                    <div className="space-y-4">
                      {messages.map((message) => (
                        <div 
                          key={message.id} 
                          className={`flex ${message.sender === 'user' ? 'justify-end' : 'justify-start'}`}
                        >
                          <div 
                            className={`max-w-[80%] p-4 rounded-2xl ${
                              message.sender === 'user' 
                                ? 'bg-primary text-primary-foreground shadow-sm' 
                                : 'bg-muted shadow-sm'
                            }`}
                          >
                            <p>{message.content}</p>
                            <p className="text-xs opacity-70 mt-2">
                              {message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                            </p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </ScrollArea>
                  
                  <div className="flex items-center gap-2">
                    <div className="relative flex-1">
                      <Input
                        ref={inputRef}
                        placeholder="Describe a task or ask a question..."
                        value={inputValue}
                        onChange={handleInputChange}
                        onKeyDown={handleKeyDown}
                        className="flex-1 bg-background"
                      />
                      {showMentionSelector && filteredMentions.length > 0 && (
                        <div className="absolute bottom-full left-0 right-0 mb-2 bg-background border rounded-lg shadow-lg max-h-[200px] overflow-y-auto z-50">
                          {filteredMentions.map((mention) => (
                            <button
                              key={mention.id}
                              className="w-full px-3 py-2 text-left hover:bg-muted/50 flex items-center gap-2"
                              onClick={() => handleMentionSelect(mention)}
                            >
                              <div className={mention.color}>
                                {mention.icon}
                              </div>
                              <span>{mention.name}</span>
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                    <Button onClick={handleSendMessage} size="icon" className="shrink-0">
                      <Send className="h-4 w-4" />
                    </Button>
                  </div>
                </Card>
              </TabsContent>
              
              <TabsContent value="tasks" className="mt-0 space-y-4">
                <Card className="p-6 border-none shadow-lg bg-gradient-to-b from-background to-muted/20">
                  <div className="flex justify-between items-center mb-6">
                    <h2 className="text-xl font-semibold">Your Tasks</h2>
                    <Button size="sm" className="gap-1">
                      <Plus className="h-4 w-4" />
                      New Task
                    </Button>
                  </div>
                  
                  {filteredTasks.length === 0 ? (
                    <div className="py-12 text-center">
                      <div className="mx-auto w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mb-4">
                        <ClipboardList className="h-8 w-8 text-primary" />
                      </div>
                      <h3 className="text-lg font-medium">No tasks found</h3>
                      <p className="text-sm text-muted-foreground mt-1">
                        {taskFilter === "all" 
                          ? "You don&apos;t have any tasks yet." 
                          : `You don&apos;t have any ${taskFilter.replace('_', ' ')} tasks.`}
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-4">
                      {filteredTasks.map((task) => (
                        <div key={task.id} className="p-4 border rounded-xl hover:border-primary/50 transition-colors bg-background/50">
                          <div className="flex justify-between items-start mb-3">
                            <div className="flex items-start gap-3">
                              {task.status === 'completed' ? (
                                <CheckCircle2 className="h-5 w-5 text-green-500 mt-1 shrink-0" />
                              ) : task.status === 'needs_input' ? (
                                <AlertCircle className="h-5 w-5 text-red-500 mt-1 shrink-0" />
                              ) : task.status === 'in_progress' ? (
                                <Clock className="h-5 w-5 text-blue-500 mt-1 shrink-0" />
                              ) : (
                                <ClipboardList className="h-5 w-5 text-gray-500 mt-1 shrink-0" />
                              )}
                              <div>
                                <div className="flex items-center gap-2">
                                  <h3 className="font-medium">{task.title}</h3>
                                  <span className={`text-xs font-medium ${getPriorityColor(task.priority)}`}>
                                    {task.priority.toUpperCase()}
                                  </span>
                                </div>
                                <p className="text-sm text-muted-foreground mt-1">{task.description}</p>
                              </div>
                            </div>
                            
                            <Badge 
                              variant={
                                task.status === 'needs_input' ? 'destructive' : 
                                task.status === 'in_progress' ? 'default' : 
                                task.status === 'completed' ? 'outline' : 'secondary'
                              }
                              className="ml-2"
                            >
                              {task.status.replace('_', ' ')}
                            </Badge>
                          </div>
                          
                          <div className="flex justify-between items-center text-sm">
                            <div className="flex items-center gap-8">
                              <div>
                                <span className="text-muted-foreground">Agent: </span>
                                <span className="font-medium">{task.assignedAgent}</span>
                              </div>
                              <div>
                                <span className="text-muted-foreground">Created: </span>
                                <span>{task.createdAt}</span>
                              </div>
                            </div>
                            
                            <div className="flex gap-2">
                              {task.status === 'needs_input' && (
                                <Button size="sm" variant="default" className="h-8">Provide Input</Button>
                              )}
                              <Button size="sm" variant="outline" className="h-8 gap-1">
                                Details
                                <ChevronRight className="h-3 w-3" />
                              </Button>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </Card>
              </TabsContent>
              
              <TabsContent value="notifications" className="mt-0">
                <Card className="p-6 border-none shadow-lg bg-gradient-to-b from-background to-muted/20">
                  <div className="flex justify-between items-center mb-6">
                    <h2 className="text-xl font-semibold">Notifications</h2>
                    <Button 
                      variant="outline" 
                      size="sm"
                      onClick={() => setNotifications(notifications.map(n => ({...n, isRead: true})))}
                      disabled={!unreadCount}
                    >
                      Mark all as read
                    </Button>
                  </div>
                  
                  <ScrollArea className="h-[450px]">
                    {notifications.length === 0 ? (
                      <div className="py-12 text-center">
                        <div className="mx-auto w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mb-4">
                          <Bell className="h-8 w-8 text-primary" />
                        </div>
                        <h3 className="text-lg font-medium">No notifications</h3>
                        <p className="text-sm text-muted-foreground mt-1">
                          You&apos;re all caught up!
                        </p>
                      </div>
                    ) : (
                      <div className="space-y-4">
                        {notifications.map((notification) => (
                          <div 
                            key={notification.id} 
                            className={`p-4 border rounded-xl cursor-pointer hover:border-primary/50 transition-colors ${
                              notification.isRead ? 'bg-background/50' : 'bg-primary/5'
                            }`}
                            onClick={() => markNotificationAsRead(notification.id)}
                          >
                            <div className="flex items-start gap-3">
                              {notification.type === 'info' && <Bell className="h-5 w-5 text-primary mt-0.5" />}
                              {notification.type === 'warning' && <Clock className="h-5 w-5 text-yellow-500 mt-0.5" />}
                              {notification.type === 'error' && <AlertCircle className="h-5 w-5 text-red-500 mt-0.5" />}
                              <div className="flex-1">
                                <div className="flex items-center justify-between">
                                  <h3 className="font-medium">{notification.title}</h3>
                                  <p className="text-xs text-muted-foreground">{notification.time}</p>
                                </div>
                                <p className="text-sm text-muted-foreground mt-1">{notification.message}</p>
                              </div>
                              {!notification.isRead && (
                                <div className="h-2 w-2 bg-primary rounded-full shrink-0 mt-2" />
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </ScrollArea>
                </Card>
              </TabsContent>
            </Tabs>
          </div>

          <div className="lg:col-span-4 space-y-6">
            <Card className="p-6 border-none shadow-lg bg-gradient-to-b from-background to-muted/20">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-xl font-semibold">Workplace Resources</h2>
                <Button variant="ghost" size="sm" className="text-xs h-7">View All</Button>
              </div>
              
              <div className="space-y-4">
                {currentResources.map((resource) => (
                  <div 
                    key={resource.id} 
                    className="flex items-start p-3 rounded-xl hover:bg-muted/50 transition-colors"
                  >
                    <div className={`mr-3 mt-0.5 ${getResourceColor(resource.type)}`}>
                      {getResourceIcon(resource.type)}
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <p className="font-medium">{resource.name}</p>
                        <Badge 
                          variant={resource.status === "active" ? "default" : "secondary"}
                          className="text-xs"
                        >
                          {resource.status}
                        </Badge>
                      </div>
                      <p className="text-sm text-muted-foreground">{resource.description}</p>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
            
            <Card className="p-6 border-none shadow-lg bg-gradient-to-b from-background to-muted/20">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-xl font-semibold">Recent Activity</h2>
                <Button variant="ghost" size="sm" className="text-xs h-7">View All</Button>
              </div>
              <div className="space-y-4">
                {[
                  {
                    title: "Inventory Monitor Agent",
                    description: "Alert: Low stock detected for SKU-123",
                    time: "10 minutes ago",
                    icon: <AlertCircle className="h-4 w-4 text-red-500" />
                  },
                  {
                    title: "Customer Support Agent",
                    description: "Processed 25 support tickets",
                    time: "1 hour ago",
                    icon: <CheckCircle2 className="h-4 w-4 text-green-500" />
                  },
                  {
                    title: "Analytics Workflow",
                    description: "Generated daily marketing report",
                    time: "2 hours ago",
                    icon: <ClipboardList className="h-4 w-4 text-blue-500" />
                  }
                ].map((activity, index) => (
                  <div key={index} className="flex items-start p-3 rounded-xl hover:bg-muted/50 transition-colors">
                    <div className="mr-3 mt-0.5">{activity.icon}</div>
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
        </div>
      </div>
    </div>
  );
} 