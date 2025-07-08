"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Server, Globe, Wrench } from "lucide-react";
import Link from "next/link";

export function ActionCards() {
  const handleScrollToSpecs = () => {
    document.getElementById('specs-section')?.scrollIntoView({ behavior: 'smooth' });
  };

  return (
    <div className="mb-6">
      <h2 className="text-lg font-semibold mb-3">🚀 Quick Actions</h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <Card className="cursor-pointer hover:shadow-md transition-all duration-200 hover:scale-[1.02]">
          <CardHeader className="text-center pb-2 pt-4">
            <div className="mx-auto mb-2 w-8 h-8 rounded-lg bg-blue-100 dark:bg-blue-900/20 flex items-center justify-center">
              <Globe className="h-4 w-4 text-blue-600 dark:text-blue-400" />
            </div>
            <CardTitle className="text-sm font-medium">🔗 FROM URL</CardTitle>
          </CardHeader>
          <CardContent className="pt-0 pb-4">
            <CardDescription className="text-xs text-center mb-3">
              Connect any MCP server by URL
            </CardDescription>
            <Button size="sm" className="w-full h-7 text-xs" asChild>
              <Link href="/mcp-servers/add">Enter URL</Link>
            </Button>
          </CardContent>
        </Card>

        <Card className="cursor-pointer hover:shadow-md transition-all duration-200 hover:scale-[1.02]">
          <CardHeader className="text-center pb-2 pt-4">
            <div className="mx-auto mb-2 w-8 h-8 rounded-lg bg-green-100 dark:bg-green-900/20 flex items-center justify-center">
              <Server className="h-4 w-4 text-green-600 dark:text-green-400" />
            </div>
            <CardTitle className="text-sm font-medium">📦 FROM SPECS</CardTitle>
          </CardHeader>
          <CardContent className="pt-0 pb-4">
            <CardDescription className="text-xs text-center mb-3">
              Browse pre-configured MCPs
            </CardDescription>
            <Button size="sm" className="w-full h-7 text-xs" onClick={handleScrollToSpecs}>
              Browse Below
            </Button>
          </CardContent>
        </Card>

        <Card className="cursor-pointer hover:shadow-md transition-all duration-200 hover:scale-[1.02]">
          <CardHeader className="text-center pb-2 pt-4">
            <div className="mx-auto mb-2 w-8 h-8 rounded-lg bg-purple-100 dark:bg-purple-900/20 flex items-center justify-center">
              <Wrench className="h-4 w-4 text-purple-600 dark:text-purple-400" />
            </div>
            <CardTitle className="text-sm font-medium">🛠️ CREATE NEW</CardTitle>
          </CardHeader>
          <CardContent className="pt-0 pb-4">
            <CardDescription className="text-xs text-center mb-3">
              Build custom MCP configuration
            </CardDescription>
            <Button size="sm" className="w-full h-7 text-xs" variant="outline" disabled>
              Build Custom
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
} 