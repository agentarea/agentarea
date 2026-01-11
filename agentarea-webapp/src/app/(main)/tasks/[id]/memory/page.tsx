import { Brain } from "lucide-react";

export default function TaskMemoryPage() {
  return (
    <div className="main-content">
      <h3 className="text-lg font-semibold">Memory Context</h3>
      <p className="note">
        Current memory state and context information
      </p>
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
    </div>
  );
}

