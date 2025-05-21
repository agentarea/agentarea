"use client";

import React, { useState, useRef } from "react";
import { Card } from "@/components/ui/card";
import { 
  Bot, 
  MessageSquare, 
  Send, 
  Bell, 
  CheckCircle2, 
  Clock,
  AlertCircle,
  Plus,
  ChevronRight,
  Building2,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
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
  hasUpdates?: boolean;
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
  const [selectedWorkplace, setSelectedWorkplace] = useState<string>("personal");
  const inputRef = useRef<HTMLInputElement>(null);
  
  // Sample workplaces data
  const workplaces = [
    { id: "personal", name: "Personal Workspace", icon: <Building2 className="h-4 w-4" /> },
    { id: "team1", name: "Marketing Team", icon: <Building2 className="h-4 w-4" /> },
    { id: "team2", name: "Development Team", icon: <Building2 className="h-4 w-4" /> },
    { id: "team3", name: "Sales Team", icon: <Building2 className="h-4 w-4" /> },
  ];
  
  // Sample data for tasks and notifications
  const [tasks] = useState<Task[]>([
    {
      id: "task-1",
      title: "Analyze Q1 Sales Data",
      description: "Generate insights from Q1 sales data and create a summary report",
      status: "in_progress",
      priority: "high",
      assignedAgent: "Data Analytics Agent",
      createdAt: "2 hours ago",
      hasUpdates: true
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
      createdAt: "2 days ago",
      hasUpdates: true
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

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setInputValue(e.target.value);
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
  
  // Get tasks that need input
  const tasksNeedingInput = tasks.filter(task => task.status === "needs_input");
  
  // Get tasks with updates
  const tasksWithUpdates = tasks.filter(task => task.hasUpdates);

  const getStatusTagClasses = (status: string) => {
    switch(status) {
      case 'in_progress': return 'bg-blue-100 text-blue-800';
      case 'completed': return 'bg-green-100 text-green-800';
      default: return 'bg-gray-100 text-gray-800';
    }
  };

  return (
    <div className="min-h-screen">
      <div className="p-8 max-w-7xl mx-auto">
        <div className="mb-8">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-4xl font-bold tracking-tight text-indigo-500">
                Workplace
              </h1>
              <p className="text-lg text-gray-500 mt-2">
                Your command center for managing agents and tasks
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Select value={selectedWorkplace} onValueChange={setSelectedWorkplace}>
                <SelectTrigger className="w-[200px] h-9 text-sm bg-white border-gray-200">
                  <div className="flex items-center gap-2">
                    <Building2 className="h-4 w-4" />
                    <SelectValue placeholder="Select workplace" />
                  </div>
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
              <Button size="icon" variant="outline" className="h-9 w-9 border-gray-200">
                <Plus className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Task creation and chat section */}
          <div className="lg:col-span-2">
            <Card className="p-6 border border-gray-200 shadow-sm bg-white rounded-xl">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <MessageSquare className="h-5 w-5 text-indigo-500" />
                  <h2 className="text-lg font-semibold">New Task</h2>
                </div>
                <Badge variant="outline" className="flex gap-1 items-center border-gray-200">
                  <Bot className="h-3 w-3" />
                  <span>Agents Ready</span>
                </Badge>
              </div>
              
              <div className="mb-4">
                <div className="relative">
                  <Input
                    ref={inputRef}
                    placeholder="Describe a task for agents to perform..."
                    value={inputValue}
                    onChange={handleInputChange}
                    className="bg-white border-gray-200 pr-24 py-6 pl-4 rounded-lg"
                    onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
                  />
                  <Button 
                    onClick={handleSendMessage} 
                    className="absolute right-1 top-1/2 transform -translate-y-1/2 px-4 bg-indigo-500 hover:bg-indigo-600"
                  >
                    <Send className="h-4 w-4 mr-2" />
                    <span>Send</span>
                  </Button>
                </div>
                <p className="text-xs text-gray-500 mt-2">
                  Describe what you want agents to do, or ask a question.
                </p>
              </div>
              
              <ScrollArea className="h-[280px] pr-4">
                <div className="space-y-4">
                  {messages.map((message) => (
                    <div 
                      key={message.id} 
                      className={`flex ${message.sender === 'user' ? 'justify-end' : 'justify-start'}`}
                    >
                      <div 
                        className={`max-w-[80%] p-4 rounded-xl ${
                          message.sender === 'user' 
                            ? 'bg-indigo-500 text-white' 
                            : 'bg-gray-100 text-gray-900'
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
            </Card>
          </div>
          
          {/* Notifications section */}
          <div>
            <Card className="p-6 border border-gray-200 shadow-sm bg-white rounded-xl">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <Bell className="h-5 w-5 text-indigo-500" />
                  <h2 className="text-lg font-semibold">Notifications</h2>
                  {unreadCount > 0 && (
                    <Badge variant="destructive" className="ml-1 bg-red-100 text-red-800 hover:bg-red-100">{unreadCount}</Badge>
                  )}
                </div>
                <Button 
                  variant="ghost" 
                  size="sm"
                  onClick={() => setNotifications(notifications.map(n => ({...n, isRead: true})))}
                  disabled={!unreadCount}
                  className="text-xs h-7 text-gray-500 hover:text-gray-700"
                >
                  Clear all
                </Button>
              </div>
              
              <ScrollArea className="max-h-[350px]">
                <div className="space-y-3">
                  {notifications.length === 0 ? (
                    <div className="py-8 text-center">
                      <p className="text-sm text-gray-500">No new notifications</p>
                    </div>
                  ) : (
                    notifications.map((notification) => (
                      <div 
                        key={notification.id} 
                        className={`p-3 border rounded-lg cursor-pointer hover:border-indigo-200 transition-colors ${
                          notification.isRead ? 'bg-white' : 'bg-indigo-50'
                        }`}
                        onClick={() => markNotificationAsRead(notification.id)}
                      >
                        <div className="flex items-start gap-2">
                          {notification.type === 'info' && <Bell className="h-4 w-4 text-indigo-500 mt-0.5" />}
                          {notification.type === 'warning' && <Clock className="h-4 w-4 text-amber-500 mt-0.5" />}
                          {notification.type === 'error' && <AlertCircle className="h-4 w-4 text-red-500 mt-0.5" />}
                          <div className="flex-1">
                            <div className="flex items-center justify-between">
                              <h3 className="text-sm font-medium">{notification.title}</h3>
                              <p className="text-xs text-gray-500">{notification.time}</p>
                            </div>
                            <p className="text-xs text-gray-500 mt-1">{notification.message}</p>
                          </div>
                          {!notification.isRead && (
                            <div className="h-2 w-2 bg-indigo-500 rounded-full shrink-0 mt-1" />
                          )}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </ScrollArea>
            </Card>
          </div>
        </div>
        
        {/* Tasks sections */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">
          {/* Tasks needing input */}
          <Card className="p-6 border border-gray-200 shadow-sm bg-white rounded-xl">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <AlertCircle className="h-5 w-5 text-red-500" />
                <h2 className="text-lg font-semibold">Tasks Needing Your Input</h2>
              </div>
              <Badge variant="outline" className="border-gray-200">{tasksNeedingInput.length}</Badge>
            </div>
            
            <ScrollArea className="max-h-[320px]">
              <div className="space-y-3">
                {tasksNeedingInput.length === 0 ? (
                  <div className="py-8 text-center">
                    <p className="text-sm text-gray-500">No tasks need your input right now</p>
                  </div>
                ) : (
                  tasksNeedingInput.map((task) => (
                    <div key={task.id} className="p-4 border border-gray-200 rounded-lg hover:border-indigo-200 transition-colors bg-white">
                      <div className="flex items-start gap-3 mb-3">
                        <AlertCircle className="h-4 w-4 text-red-500 mt-1 shrink-0" />
                        <div className="flex-1">
                          <div className="flex items-center justify-between">
                            <h3 className="text-sm font-medium">{task.title}</h3>
                            <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                              task.priority === 'high' ? 'bg-red-100 text-red-800' : 
                              task.priority === 'medium' ? 'bg-amber-100 text-amber-800' : 
                              'bg-green-100 text-green-800'
                            }`}>
                              {task.priority.toUpperCase()}
                            </span>
                          </div>
                          <p className="text-xs text-gray-500 mt-1">{task.description}</p>
                        </div>
                      </div>
                      
                      <div className="flex justify-between items-center text-xs mt-3">
                        <div className="text-gray-500">
                          <span>Agent: </span>
                          <span className="font-medium text-gray-700">{task.assignedAgent}</span>
                        </div>
                        
                        <Button size="sm" className="h-7 text-xs bg-indigo-500 hover:bg-indigo-600">
                          Provide Input
                        </Button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </ScrollArea>
          </Card>
          
          {/* Recent updates */}
          <Card className="p-6 border border-gray-200 shadow-sm bg-white rounded-xl">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Clock className="h-5 w-5 text-blue-500" />
                <h2 className="text-lg font-semibold">Recent Updates</h2>
              </div>
              <Button variant="ghost" size="sm" className="text-xs h-7 text-gray-500 hover:text-gray-700">View All</Button>
            </div>
            
            <ScrollArea className="max-h-[320px]">
              <div className="space-y-3">
                {tasksWithUpdates.length === 0 ? (
                  <div className="py-8 text-center">
                    <p className="text-sm text-gray-500">No recent updates</p>
                  </div>
                ) : (
                  tasksWithUpdates.map((task) => (
                    <div key={task.id} className="p-4 border border-gray-200 rounded-lg hover:border-indigo-200 transition-colors bg-white">
                      <div className="flex items-start gap-3 mb-3">
                        {task.status === 'completed' ? (
                          <CheckCircle2 className="h-4 w-4 text-green-500 mt-1 shrink-0" />
                        ) : (
                          <Clock className="h-4 w-4 text-blue-500 mt-1 shrink-0" />
                        )}
                        <div className="flex-1">
                          <div className="flex items-center justify-between">
                            <h3 className="text-sm font-medium">{task.title}</h3>
                            <span className={`text-xs px-2 py-0.5 rounded-full ${getStatusTagClasses(task.status)}`}>
                              {task.status.replace('_', ' ')}
                            </span>
                          </div>
                          <p className="text-xs text-gray-500 mt-1">{task.description}</p>
                        </div>
                      </div>
                      
                      <div className="flex justify-between items-center text-xs mt-3">
                        <div className="text-gray-500">
                          <span>Updated: </span>
                          <span>{task.createdAt}</span>
                        </div>
                        
                        <Button size="sm" variant="outline" className="h-7 text-xs gap-1 border-gray-200 text-gray-700 hover:bg-gray-50">
                          View Details
                          <ChevronRight className="h-3 w-3" />
                        </Button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </ScrollArea>
          </Card>
        </div>
      </div>
    </div>
  );
} 