import { Brain } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function TaskMemoryPage() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Memory Context</CardTitle>
        <CardDescription>
          Current memory state and context information
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="py-12 text-center">
          <Brain className="mx-auto mb-4 h-16 w-16 text-muted-foreground opacity-50" />
          <h3 className="mb-2 text-lg font-semibold">Memory Context</h3>
          <p className="mb-4 text-muted-foreground">
            Memory context information is not yet available through the current
            API.
          </p>
          <p className="text-xs text-muted-foreground">
            This feature will be implemented in future versions to show task
            memory state and context.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

