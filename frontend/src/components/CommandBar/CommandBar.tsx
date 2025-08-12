"use client"

import { useState, useEffect, useCallback } from 'react';
import { Search, Command, Home, Bot, Server, Settings, Plus, List, Zap, User, Store, Wrench } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { cn } from '@/lib/utils';
import { useRouter } from 'next/navigation';

interface CommandBarProps {
  isCollapsed?: boolean;
}

interface Command {
  id: number;
  title: string;
  shortcut: string;
  url: string;
  icon: React.ComponentType<{ className?: string }>;
  category: 'navigation' | 'actions' | 'settings';
}

export default function CommandBar({ isCollapsed }: CommandBarProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const router = useRouter();

  // Enhanced commands with icons and categories
  const commands: Command[] = [
    // Navigation
    { id: 1, title: 'Go to Dashboard', shortcut: 'gd', url: '/', icon: Home, category: 'navigation' },
    { id: 2, title: 'Go to Tasks', shortcut: 'gt', url: '/tasks', icon: List, category: 'navigation' },
    { id: 3, title: 'Go to Agents', shortcut: 'ga', url: '/agents', icon: Bot, category: 'navigation' },
    { id: 4, title: 'Go to MCP Servers', shortcut: 'gm', url: '/mcp-servers', icon: Server, category: 'navigation' },
    { id: 5, title: 'Go to MCP Marketplace', shortcut: 'gmp', url: '/mcp-servers/marketplace', icon: Store, category: 'navigation' },
    { id: 6, title: 'Go to MCP Tools', shortcut: 'gmt', url: '/mcp-servers/tools', icon: Wrench, category: 'navigation' },
    { id: 7, title: 'Go to Settings', shortcut: 'gs', url: '/settings', icon: Settings, category: 'navigation' },
    
    // Actions
    { id: 8, title: 'Create New Agent', shortcut: 'na', url: '/agents/new', icon: Plus, category: 'actions' },
    { id: 9, title: 'Add MCP Server', shortcut: 'nm', url: '/mcp-servers/add', icon: Plus, category: 'actions' },
    { id: 8, title: 'Deploy Agent', shortcut: 'da', url: '/agents/deploy', icon: Zap, category: 'actions' },
    
    // Settings
    { id: 9, title: 'Account Settings', shortcut: 'as', url: '/settings#profile', icon: User, category: 'settings' },
    { id: 10, title: 'Preferences', shortcut: 'pr', url: '/settings#preferences', icon: Settings, category: 'settings' },
  ];

  const filteredCommands = commands.filter(command =>
    command.title.toLowerCase().includes(search.toLowerCase()) ||
    command.shortcut.toLowerCase().includes(search.toLowerCase())
  );

  // Handle keyboard shortcuts
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      setIsOpen(true);
      setSelectedIndex(0);
    }
  }, []);

  // Handle dialog keyboard navigation
  const handleDialogKeyDown = useCallback((e: KeyboardEvent) => {
    if (!isOpen) return;

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setSelectedIndex(prev => 
          prev < filteredCommands.length - 1 ? prev + 1 : 0
        );
        break;
      case 'ArrowUp':
        e.preventDefault();
        setSelectedIndex(prev => 
          prev > 0 ? prev - 1 : filteredCommands.length - 1
        );
        break;
      case 'Enter':
        e.preventDefault();
        if (filteredCommands[selectedIndex]) {
          handleCommand(filteredCommands[selectedIndex].url);
        }
        break;
      case 'Escape':
        e.preventDefault();
        setIsOpen(false);
        break;
    }
  }, [isOpen, filteredCommands, selectedIndex]);

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    document.addEventListener('keydown', handleDialogKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('keydown', handleDialogKeyDown);
    };
  }, [handleKeyDown, handleDialogKeyDown]);

  // Reset selected index when search changes
  useEffect(() => {
    setSelectedIndex(0);
  }, [search]);

  const handleCommand = (url: string) => {
    setIsOpen(false);
    setSearch('');
    setSelectedIndex(0);
    router.push(url);
  };

  const getCategoryTitle = (category: string) => {
    switch (category) {
      case 'navigation': return 'Navigation';
      case 'actions': return 'Actions';
      case 'settings': return 'Settings';
      default: return 'Commands';
    }
  };

  // Group commands by category
  const groupedCommands = filteredCommands.reduce((groups, command) => {
    const category = command.category;
    if (!groups[category]) {
      groups[category] = [];
    }
    groups[category].push(command);
    return groups;
  }, {} as Record<string, Command[]>);

  return (
    <>
      {/* Slim Command Bar Trigger Button */}
      <button
        onClick={() => setIsOpen(true)}
        className={cn(
          "flex items-center gap-2 w-full px-2 py-1.5 text-xs text-muted-foreground",
          "bg-muted/30 hover:bg-muted/60 rounded transition-colors",
          "border border-transparent hover:border-border/30",
          isCollapsed && "justify-center px-1.5"
        )}
      >
        <Search className="h-3.5 w-3.5 flex-shrink-0" />
        {!isCollapsed && (
          <>
            <span className="flex-1 text-left truncate">Search or command...</span>
            <div className="flex items-center">
              <Badge variant="outline" className="px-1 py-0 text-xs h-4 border-muted-foreground/20">
                ⌘K
              </Badge>
            </div>
          </>
        )}
      </button>

      {/* Compact Command Bar Dialog */}
      <Dialog open={isOpen} onOpenChange={setIsOpen}>
        <DialogContent className="sm:max-w-[480px] p-0 gap-0">
          <div className="p-3 border-b">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 transform -translate-y-1/2 text-muted-foreground h-3.5 w-3.5" />
              <Input
                placeholder="Search commands..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-8 h-8 text-sm border-0 focus-visible:ring-0 bg-transparent"
                autoFocus
              />
            </div>
          </div>

          <div className="max-h-[280px] overflow-y-auto">
            {filteredCommands.length > 0 ? (
              <div className="py-1">
                {Object.entries(groupedCommands).map(([category, categoryCommands]) => (
                  <div key={category}>
                    <div className="px-3 py-1 text-xs font-medium text-muted-foreground/70">
                      {getCategoryTitle(category)}
                    </div>
                    {categoryCommands.map((command, categoryIndex) => {
                      const globalIndex = filteredCommands.findIndex(c => c.id === command.id);
                      const IconComponent = command.icon;
                      
                      return (
                        <button
                          key={command.id}
                          onClick={() => handleCommand(command.url)}
                          className={cn(
                            "w-full flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-muted transition-colors text-left group",
                            globalIndex === selectedIndex && "bg-muted"
                          )}
                        >
                          <IconComponent className="h-3.5 w-3.5 text-muted-foreground/70 group-hover:text-foreground" />
                          <span className="flex-1">{command.title}</span>
                          <span className="text-xs text-muted-foreground/50 font-mono">
                            {command.shortcut}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                ))}
              </div>
            ) : (
              <div className="py-6 text-center text-sm text-muted-foreground">
                <Search className="h-6 w-6 mx-auto mb-2 opacity-40" />
                <p className="text-xs">No commands found</p>
              </div>
            )}
          </div>

          <div className="border-t px-3 py-1.5 text-xs text-muted-foreground/60 bg-muted/20">
            <span>↑↓ navigate • ⏎ select • esc close</span>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}