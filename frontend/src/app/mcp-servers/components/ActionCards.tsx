"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Server, Globe, Wrench, ArrowRight, Sparkles } from "lucide-react";
import Link from "next/link";

export function ActionCards() {
  const handleScrollToSpecs = () => {
    document.getElementById('specs-section')?.scrollIntoView({ behavior: 'smooth' });
  };

  const actionCards = [
    {
      icon: Globe,
      title: "Connect by URL",
      description: "Connect any server using its endpoint URL",
      action: "Enter URL",
      href: "/mcp-servers/add",
      gradient: "from-blue-500 to-cyan-500",
      bgColor: "bg-blue-50 dark:bg-blue-950/30",
      iconColor: "text-blue-600 dark:text-blue-400",
      borderColor: "border-blue-200 dark:border-blue-800",
      hoverBg: "hover:bg-blue-100 dark:hover:bg-blue-950/50"
    },
    {
      icon: Server,
      title: "Browse Catalog",
      description: "Choose from verified server templates",
      action: "Browse Below",
      onClick: handleScrollToSpecs,
      gradient: "from-green-500 to-emerald-500",
      bgColor: "bg-green-50 dark:bg-green-950/30",
      iconColor: "text-green-600 dark:text-green-400",
      borderColor: "border-green-200 dark:border-green-800",
      hoverBg: "hover:bg-green-100 dark:hover:bg-green-950/50"
    },
    {
      icon: Wrench,
      title: "Create Custom",
      description: "Advanced: Build your own server configuration",
      action: "Coming Soon",
      disabled: true,
      gradient: "from-purple-500 to-violet-500",
      bgColor: "bg-purple-50 dark:bg-purple-950/30",
      iconColor: "text-purple-600 dark:text-purple-400",
      borderColor: "border-purple-200 dark:border-purple-800",
      hoverBg: "hover:bg-purple-100 dark:hover:bg-purple-950/50"
    }
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-primary to-primary/80 flex items-center justify-center">
          <Sparkles className="h-4 w-4 text-white" />
        </div>
        <div>
          <h2 className="text-2xl font-bold">Quick Start</h2>
          <p className="text-muted-foreground">Get your first MCP server up and running</p>
        </div>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {actionCards.map((card, index) => {
          const IconComponent = card.icon;
          
          return (
            <Card 
              key={index}
              className={`group relative overflow-hidden transition-all duration-300 hover:shadow-xl hover:shadow-black/5 hover:-translate-y-1 ${card.bgColor} border-2 ${card.borderColor} ${card.hoverBg}`}
            >
              {/* Gradient overlay */}
              <div className={`absolute inset-0 bg-gradient-to-br ${card.gradient} opacity-0 group-hover:opacity-5 transition-opacity duration-300`} />
              
              <CardHeader className="text-center pb-4 relative">
                <div className={`mx-auto mb-4 w-16 h-16 rounded-2xl ${card.bgColor} border-2 ${card.borderColor} flex items-center justify-center group-hover:scale-110 transition-transform duration-300`}>
                  <IconComponent className={`h-8 w-8 ${card.iconColor}`} />
                </div>
                <CardTitle className="text-lg font-semibold group-hover:text-primary transition-colors">
                  {card.title}
                </CardTitle>
              </CardHeader>
              
              <CardContent className="text-center space-y-4 relative">
                <CardDescription className="text-sm leading-relaxed min-h-[2.5rem] flex items-center justify-center">
                  {card.description}
                </CardDescription>
                
                {card.href ? (
                  <Button 
                    size="sm" 
                    className={`w-full group/btn transition-all duration-200 ${card.disabled ? 'opacity-50 cursor-not-allowed' : 'hover:shadow-lg'}`}
                    asChild={!card.disabled}
                    disabled={card.disabled}
                  >
                    <Link href={card.href} className="flex items-center gap-2">
                      {card.action}
                      <ArrowRight className="h-4 w-4 group-hover/btn:translate-x-1 transition-transform" />
                    </Link>
                  </Button>
                ) : (
                  <Button 
                    size="sm" 
                    className={`w-full group/btn transition-all duration-200 ${card.disabled ? 'opacity-50 cursor-not-allowed' : 'hover:shadow-lg'}`}
                    onClick={card.onClick}
                    disabled={card.disabled}
                    variant={card.disabled ? "outline" : "default"}
                  >
                    <span className="flex items-center gap-2">
                      {card.action}
                      {!card.disabled && <ArrowRight className="h-4 w-4 group-hover/btn:translate-x-1 transition-transform" />}
                    </span>
                  </Button>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>
      
      {/* Help text */}
      <div className="text-center">
        <p className="text-sm text-muted-foreground">
          New to MCP servers? Start with our verified templates below, or check out the{" "}
          <a href="#" className="text-primary hover:underline font-medium">
            documentation
          </a>{" "}
          for detailed setup guides.
        </p>
      </div>
    </div>
  );
}