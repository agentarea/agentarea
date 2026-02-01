import { AlertTriangle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

interface TaskErrorCardProps {
  errorMessage?: string;
}

export default function TaskErrorCard({ errorMessage }: TaskErrorCardProps) {
  if (!errorMessage) {
    return null;
  }

  return (
    <Card className="border-destructive">
      <CardContent className="pb-3 pt-3">
        <div className="flex items-center gap-2 text-destructive">
          <AlertTriangle className="h-4 w-4" />
          <span className="text-sm font-medium">Error</span>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">{errorMessage}</p>
      </CardContent>
    </Card>
  );
}

