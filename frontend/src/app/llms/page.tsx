import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Cpu, Download, Plus } from "lucide-react";
import Link from "next/link";
import { listLLMModels } from "@/lib/api";

export default async function BrowseLLMsPage() {
  const { data: models } = await listLLMModels();
  
  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-6">
        <Input
          placeholder="Search LLM models..."
          // value={searchQuery}
          // onChange={(e) => setSearchQuery(e.target.value)}
          className="max-w-md"
        />
        <Button asChild>
          <Link href="/marketplace/llms/create" className="flex items-center gap-1">
            <Plus className="h-4 w-4" />
            Add Model
          </Link>
        </Button>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {models && models.map((model) => (
          <Card key={model.id} className="flex flex-col">
            <CardHeader>
              <div className="flex justify-between items-start">
                <div className="flex items-center gap-2">
                  <Cpu className="h-5 w-5 text-primary" />
                  <CardTitle>{model.name}</CardTitle>
                </div>
                {model.verified && (
                  <Badge variant="secondary">Verified</Badge>
                )}
              </div>
              <CardDescription>{model.description}</CardDescription>
            </CardHeader>
            <CardContent className="flex-grow">
              <div className="flex flex-wrap gap-2 mb-3">
                {model.tags && model.tags.map((tag) => (
                  <Badge key={tag} variant="outline">{tag}</Badge>
                ))}
              </div>
              <p className="text-sm text-muted-foreground">By {model.provider} • {model.rating} rating</p>
            </CardContent>
            <CardFooter className="flex justify-between">
              <Button variant="outline" size="sm">View Details</Button>
              <Button size="sm" className="flex items-center gap-1">
                <Download className="h-4 w-4" />
                Install
              </Button>
            </CardFooter>
          </Card>
        ))}
      </div>
    </div>
  );
} 